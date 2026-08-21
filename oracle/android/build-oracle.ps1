param(
    [Parameter(Mandatory = $true)] [string] $SdkRoot,
    [Parameter(Mandatory = $true)] [string] $JavaHome
)

$ErrorActionPreference = 'Stop'
$env:JAVA_HOME = $JavaHome
$env:Path = (Join-Path $JavaHome 'bin') + [IO.Path]::PathSeparator + $env:Path
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspace = Resolve-Path (Join-Path $project '..\..')
$build = Join-Path $project 'build'
$buildTools = Get-ChildItem -LiteralPath (Join-Path $SdkRoot 'build-tools') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$platform = Get-ChildItem -LiteralPath (Join-Path $SdkRoot 'platforms') -Directory | Sort-Object Name -Descending | Select-Object -First 1
if (-not $buildTools -or -not $platform) { throw 'Android build tools/platform are missing.' }

New-Item -ItemType Directory -Force -Path $build,(Join-Path $build 'classes'),(Join-Path $build 'dex'),(Join-Path $build 'stage\lib\arm64-v8a') | Out-Null
Copy-Item -LiteralPath (Join-Path $workspace '.analysis\apk\lib\arm64-v8a\libPPPP_API.so') -Destination (Join-Path $build 'stage\lib\arm64-v8a\libPPPP_API.so') -Force

$androidJar = Join-Path $platform.FullName 'android.jar'
$aapt2 = Join-Path $buildTools.FullName 'aapt2.exe'
$d8 = Join-Path $buildTools.FullName 'd8.bat'
$zipalign = Join-Path $buildTools.FullName 'zipalign.exe'
$apksigner = Join-Path $buildTools.FullName 'apksigner.bat'
$javac = Join-Path $JavaHome 'bin\javac.exe'
$jar = Join-Path $JavaHome 'bin\jar.exe'
$keytool = Join-Path $JavaHome 'bin\keytool.exe'

& $aapt2 link -I $androidJar --manifest (Join-Path $project 'AndroidManifest.xml') --min-sdk-version 23 --target-sdk-version 35 --version-code 1 --version-name 1.0 -o (Join-Path $build 'unsigned-base.apk')
if ($LASTEXITCODE -ne 0) { throw "aapt2 failed with exit code $LASTEXITCODE" }
$sources = Get-ChildItem -LiteralPath (Join-Path $project 'src') -Filter '*.java' -File -Recurse | Select-Object -ExpandProperty FullName
& $javac --release 8 -encoding UTF-8 -classpath $androidJar -d (Join-Path $build 'classes') $sources
if ($LASTEXITCODE -ne 0) { throw "javac failed with exit code $LASTEXITCODE" }
& $jar --create --file (Join-Path $build 'classes.jar') -C (Join-Path $build 'classes') .
if ($LASTEXITCODE -ne 0) { throw "jar failed with exit code $LASTEXITCODE" }
& $d8 --lib $androidJar --output (Join-Path $build 'dex') (Join-Path $build 'classes.jar')
if ($LASTEXITCODE -ne 0) { throw "d8 failed with exit code $LASTEXITCODE" }
Copy-Item -LiteralPath (Join-Path $build 'unsigned-base.apk') -Destination (Join-Path $build 'unsigned.apk') -Force
Push-Location (Join-Path $build 'dex')
try { & $jar --update --file (Join-Path $build 'unsigned.apk') 'classes.dex' } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "jar dex update failed with exit code $LASTEXITCODE" }
Push-Location (Join-Path $build 'stage')
try { & $jar --update --file (Join-Path $build 'unsigned.apk') 'lib/arm64-v8a/libPPPP_API.so' } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "jar native-library update failed with exit code $LASTEXITCODE" }
& $zipalign -f 4 (Join-Path $build 'unsigned.apk') (Join-Path $build 'aligned.apk')
if ($LASTEXITCODE -ne 0) { throw "zipalign failed with exit code $LASTEXITCODE" }

$keystore = Join-Path $build 'debug.keystore'
if (-not (Test-Path -LiteralPath $keystore)) {
    & $keytool -genkeypair -keystore $keystore -storepass android -keypass android -alias androiddebugkey -dname 'CN=Android Debug,O=Android,C=US' -keyalg RSA -keysize 2048 -validity 10000
    if ($LASTEXITCODE -ne 0) { throw "keytool failed with exit code $LASTEXITCODE" }
}
& $apksigner sign --ks $keystore --ks-pass pass:android --key-pass pass:android --out (Join-Path $build 'yi-tnp-oracle.apk') (Join-Path $build 'aligned.apk')
if ($LASTEXITCODE -ne 0) { throw "apksigner failed with exit code $LASTEXITCODE" }
& $apksigner verify --verbose (Join-Path $build 'yi-tnp-oracle.apk')
if ($LASTEXITCODE -ne 0) { throw "apksigner verify failed with exit code $LASTEXITCODE" }
