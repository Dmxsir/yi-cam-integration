#!/usr/bin/env bash
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="$(cd "$PROJECT/../.." && pwd)"
BUILD="$PROJECT/build"

SDK_ROOT="${ANDROID_SDK_ROOT:-/usr/lib/android-sdk}"
BUILD_TOOLS="$SDK_ROOT/build-tools/34.0.0"
ANDROID_JAR="$SDK_ROOT/platforms/android-34/android.jar"

AAPT2="$BUILD_TOOLS/aapt2"
D8="$BUILD_TOOLS/d8"
ZIPALIGN="$BUILD_TOOLS/zipalign"
APKSIGNER="$BUILD_TOOLS/apksigner"

NATIVE="$WORKSPACE/.analysis/apk/lib/arm64-v8a/libPPPP_API.so"

for f in "$AAPT2" "$D8" "$ZIPALIGN" "$APKSIGNER" "$ANDROID_JAR" "$NATIVE"; do
    if [[ ! -e "$f" ]]; then
        echo "MISSING: $f" >&2
        exit 1
    fi
done

rm -rf "$BUILD"
mkdir -p \
    "$BUILD/classes" \
    "$BUILD/dex" \
    "$BUILD/stage/lib/arm64-v8a"

cp "$NATIVE" "$BUILD/stage/lib/arm64-v8a/libPPPP_API.so"

"$AAPT2" link \
    -I "$ANDROID_JAR" \
    --manifest "$PROJECT/AndroidManifest.xml" \
    --min-sdk-version 23 \
    --target-sdk-version 34 \
    --version-code 1 \
    --version-name 1.0 \
    -o "$BUILD/unsigned-base.apk"

mapfile -t SOURCES < <(find "$PROJECT/src" -type f -name '*.java' | sort)

javac \
    --release 8 \
    -encoding UTF-8 \
    -classpath "$ANDROID_JAR" \
    -d "$BUILD/classes" \
    "${SOURCES[@]}"

jar --create \
    --file "$BUILD/classes.jar" \
    -C "$BUILD/classes" .

"$D8" \
    --lib "$ANDROID_JAR" \
    --output "$BUILD/dex" \
    "$BUILD/classes.jar"

cp "$BUILD/unsigned-base.apk" "$BUILD/unsigned.apk"

(
    cd "$BUILD/dex"
    jar --update --file "$BUILD/unsigned.apk" classes.dex
)

(
    cd "$BUILD/stage"
    jar --update --file "$BUILD/unsigned.apk" \
        lib/arm64-v8a/libPPPP_API.so
)

"$ZIPALIGN" -f 4 \
    "$BUILD/unsigned.apk" \
    "$BUILD/aligned.apk"

KEYSTORE="${YI_ORACLE_KEYSTORE:-$HOME/.config/yi-cam-integration/debug.keystore}"
mkdir -p "$(dirname "$KEYSTORE")"

if [[ ! -f "$KEYSTORE" ]]; then
    keytool \
        -genkeypair \
        -keystore "$KEYSTORE" \
        -storepass android \
        -keypass android \
        -alias androiddebugkey \
        -dname 'CN=Android Debug,O=Android,C=US' \
        -keyalg RSA \
        -keysize 2048 \
        -validity 10000
fi

"$APKSIGNER" sign \
    --ks "$KEYSTORE" \
    --ks-pass pass:android \
    --key-pass pass:android \
    --out "$BUILD/yi-tnp-oracle.apk" \
    "$BUILD/aligned.apk"

"$APKSIGNER" verify --verbose \
    "$BUILD/yi-tnp-oracle.apk"

echo
echo "BUILD SUCCESS:"
ls -lh "$BUILD/yi-tnp-oracle.apk"
sha256sum "$BUILD/yi-tnp-oracle.apk"
