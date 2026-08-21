package com.local.yitnporacle;

import android.app.Activity;
import android.os.Bundle;
import android.util.Base64;
import android.widget.TextView;

import com.p2p.pppp_api.PPPP_APIs;
import com.tnp.model.st_PPPP_Session;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

public final class OracleActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        TextView text = new TextView(this);
        text.setText("YI TNP oracle running; secrets are never displayed.");
        setContentView(text);
        new Thread(new OracleRunner(), "yi-tnp-oracle").start();
    }

    private static final class OracleRunner implements Runnable {
        private static final int HOST_PORT = 27183;
        private static final int SET_RESOLUTION = 4881;
        private static final int START_REALTIME = 9029;
        private static final int START_AUDIO = 768;
        private static final int STOP_LIVE = 767;
        private static final char[] NONCE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789".toCharArray();

        private final SecureRandom random = new SecureRandom();
        private final AtomicBoolean reading = new AtomicBoolean(false);
        private final AtomicLong firstIFrameAt = new AtomicLong(0);
        private DataInputStream input;
        private DataOutputStream output;
        private int handle = -1;
        private short commandNumber;
        private byte tnpApplicationVersion = 2;
        private String did;
        private String password;
        private String noncePrefix;
        private boolean encrypted;
        private boolean liveStarted;

        @Override
        public void run() {
            boolean initialized = false;
            Socket socket = null;
            try {
                socket = connectHost();
                input = new DataInputStream(socket.getInputStream());
                output = new DataOutputStream(socket.getOutputStream());
                event("oracle_ready", new JSONObject());
                JSONObject config = readConfig();
                did = required(config, "did");
                String server = required(config, "server");
                String deviceKey = required(config, "deviceKey");
                password = required(config, "password");
                boolean wakeup = config.getBoolean("wakeup");
                encrypted = config.getBoolean("encrypted");
                int flag = config.getInt("connectionFlag");
                int resolution = config.getInt("resolution");
                int startUseCount = config.getInt("startUseCount");
                int captureSeconds = config.getInt("captureSeconds");
                noncePrefix = nonce(7);

                JSONObject secretShape = new JSONObject();
                secretShape.put("didLength", did.length());
                secretShape.put("serverLength", server.length());
                secretShape.put("deviceKeyLength", deviceKey.length());
                secretShape.put("passwordLength", password.length());
                secretShape.put("p2pEncrypt", encrypted);
                event("secret_shape", secretShape);

                long started = System.nanoTime();
                int initResult = PPPP_APIs.PPPP_Initialize(new byte[] {0}, 12);
                initialized = initResult == 0;
                event("PPPP_Initialize", callResult(initResult, started).put("maxSessions", 12));
                if (!initialized) throw new IllegalStateException("PPPP initialization failed");
                int debugResult = PPPP_APIs.PPPP_Config_Debug((byte) 0, 0);
                event("PPPP_Config_Debug", new JSONObject().put("returnValue", debugResult).put("enabled", false));
                event("PPPP_GetAPIVersion", new JSONObject().put("returnValue", PPPP_APIs.PPPP_GetAPIVersion()));

                started = System.nanoTime();
                String connectFunction;
                if (wakeup) {
                    connectFunction = "PPPP_WakeUp_And_Connect";
                    handle = PPPP_APIs.PPPP_WakeUp_And_Connect(did, (byte) flag, 0, server, deviceKey);
                } else {
                    connectFunction = "PPPP_Connect";
                    handle = PPPP_APIs.PPPP_Connect(did, (byte) flag, 0, server, deviceKey);
                }
                JSONObject connected = callResult(handle, started);
                connected.put("function", connectFunction);
                connected.put("flag", flag);
                connected.put("udpPort", 0);
                connected.put("didLength", did.length());
                connected.put("serverLength", server.length());
                connected.put("deviceKeyLength", deviceKey.length());
                event("PPPP_Connect", connected);
                if (handle < 0) throw new IllegalStateException("PPPP connection failed");

                st_PPPP_Session session = new st_PPPP_Session();
                started = System.nanoTime();
                int checkResult = PPPP_APIs.PPPP_Check(handle, session);
                JSONObject checked = callResult(checkResult, started);
                checked.put("sessionHandle", handle);
                checked.put("mode", session.getMode());
                checked.put("connectTime", session.getConnectTime());
                checked.put("connectTimeP2P", session.getConnectTimeP2P());
                checked.put("connectTimeRelay", session.getConnectTimeRelay());
                event("PPPP_Check", checked);
                if (checkResult != 0) throw new IllegalStateException("PPPP check failed");

                // Phase 2C.3 isolates one behavioral difference from the failed oracle:
                // the successful older official client sends 4881 -> 9029 -> 768 before
                // it waits for the first channel-0 response. Keep every other transport,
                // authentication, version and connection input unchanged.
                int resolutionUseCount = startUseCount - 1;
                byte[] resolutionPayload = new byte[8];
                putInt(resolutionPayload, 0, resolution);
                putInt(resolutionPayload, 4, resolutionUseCount);
                byte[] startPayload = new byte[] {(byte) startUseCount, (byte) resolution, 1, 0};
                byte[] audioPayload = new byte[8];

                // Do not emit host-side diagnostics between these writes. The official
                // capture carries all three TNP units in one DRW burst; suppressing the
                // event() flushes here gives the unchanged native PPPP library the best
                // chance to preserve the same immediate/coalesced wire behavior.
                long burstStarted = System.nanoTime();
                int resolutionCommandNumber = sendCommand(SET_RESOLUTION, resolutionPayload, false);
                int startWrite = sendCommand(START_REALTIME, startPayload, false);
                liveStarted = true;
                int audioWrite = sendCommand(START_AUDIO, audioPayload, false);
                long burstElapsedMicros = (System.nanoTime() - burstStarted) / 1_000L;

                event("startup_burst", new JSONObject()
                        .put("command1", SET_RESOLUTION)
                        .put("command1Number", resolutionCommandNumber)
                        .put("command1PayloadLength", resolutionPayload.length)
                        .put("command2", START_REALTIME)
                        .put("command2Number", startWrite)
                        .put("command2PayloadLength", startPayload.length)
                        .put("command2UseCount", startUseCount)
                        .put("command2Resolution", resolution)
                        .put("command3", START_AUDIO)
                        .put("command3Number", audioWrite)
                        .put("command3PayloadLength", audioPayload.length)
                        .put("command3Meaning", "AUDIOSTART")
                        .put("blockingReadBetweenCommands", false)
                        .put("diagnosticFlushBetweenCommands", false)
                        .put("ppppWriteCount", 3)
                        .put("tnpApplicationVersion", tnpApplicationVersion & 0xff)
                        .put("elapsedMicros", burstElapsedMicros));
                event("realtime_start", new JSONObject()
                        .put("command", START_REALTIME)
                        .put("channel", 0)
                        .put("commandNumber", startWrite)
                        .put("payloadLength", 4)
                        .put("useCount", startUseCount)
                        .put("resolution", resolution)
                        .put("commandVersion", 1)
                        .put("reserved", 0));

                // Start video readers before the first blocking channel-0 read. The
                // successful official session produced channel-2 data at ~81 ms, so the
                // readers are armed immediately after the three-command burst.
                reading.set(true);
                Thread channel2 = new Thread(() -> readFrames((byte) 2), "yi-channel-2");
                Thread channel3 = new Thread(() -> readFrames((byte) 3), "yi-channel-3");
                channel2.start();
                channel3.start();

                CommandResponse authentication = readCommandResponse();
                long firstResponseLatencyMicros = (System.nanoTime() - burstStarted) / 1_000L;
                if (authentication.version != tnpApplicationVersion) {
                    throw new IllegalStateException("Unexpected TNP application version in controlled retry");
                }
                JSONObject auth = new JSONObject();
                auth.put("authResult", authentication.authResult);
                auth.put("responseCommand", authentication.commandType);
                auth.put("responseCommandNumber", authentication.commandNumber);
                auth.put("requestCommandNumber", resolutionCommandNumber);
                auth.put("tnpApplicationVersion", authentication.version & 0xff);
                auth.put("responseLatencyMicros", firstResponseLatencyMicros);
                event("TNP_authentication", auth);
                if (authentication.authResult != 0) throw new SecurityException("TNP authentication failed");

                long waitDeadline = System.nanoTime() + 20_000_000_000L;
                while (firstIFrameAt.get() == 0 && System.nanoTime() < waitDeadline) Thread.sleep(50);
                if (firstIFrameAt.get() == 0) throw new IllegalStateException("No realtime I-frame observed");
                long captureDeadline = firstIFrameAt.get() + captureSeconds * 1_000_000_000L;
                while (System.nanoTime() < captureDeadline) Thread.sleep(50);

                byte[] stopPayload = new byte[8];
                int stopCommandNumber = sendCommand(STOP_LIVE, stopPayload);
                liveStarted = false;
                event("realtime_stop", new JSONObject().put("command", STOP_LIVE).put("channel", 0)
                        .put("commandNumber", stopCommandNumber).put("payloadLength", 8));
                reading.set(false);
                int breakResult = PPPP_APIs.PPPP_Connect_Break(did);
                event("PPPP_Connect_Break", new JSONObject().put("returnValue", breakResult).put("didLength", did.length()));
                int closeResult = PPPP_APIs.PPPP_ForceClose(handle);
                event("PPPP_ForceClose", new JSONObject().put("returnValue", closeResult).put("sessionHandle", handle));
                handle = -1;
                channel2.join(5000);
                channel3.join(5000);
                event("reader_shutdown", new JSONObject().put("channel2Stopped", !channel2.isAlive()).put("channel3Stopped", !channel3.isAlive()));
            } catch (Throwable failure) {
                safeError(failure);
            } finally {
                reading.set(false);
                if (handle >= 0) {
                    if (liveStarted) {
                        try { sendCommand(STOP_LIVE, new byte[8]); } catch (Throwable ignored) {}
                        liveStarted = false;
                    }
                    try { PPPP_APIs.PPPP_Connect_Break(did); } catch (Throwable ignored) {}
                    try { PPPP_APIs.PPPP_ForceClose(handle); } catch (Throwable ignored) {}
                    handle = -1;
                }
                if (initialized) {
                    try {
                        int result = PPPP_APIs.PPPP_DeInitialize();
                        event("PPPP_DeInitialize", new JSONObject().put("returnValue", result));
                    } catch (Throwable ignored) {}
                }
                try { event("oracle_finished", new JSONObject()); } catch (Throwable ignored) {}

                // Keep the host connection alive until all shutdown diagnostics have
                // been emitted. Closing it earlier caused the Linux host to observe
                // EOF even after a completely successful PPPP/TNP/video session.
                clearSecrets();
                input = null;
                output = null;
                if (socket != null) {
                    try { socket.close(); } catch (Throwable ignored) {}
                }
            }
        }

        private Socket connectHost() throws Exception {
            Exception last = null;
            for (int attempt = 0; attempt < 50; attempt++) {
                try {
                    Socket socket = new Socket();
                    socket.connect(new InetSocketAddress("127.0.0.1", HOST_PORT), 1000);
                    socket.setTcpNoDelay(true);
                    return socket;
                } catch (Exception failure) {
                    last = failure;
                    Thread.sleep(100);
                }
            }
            throw last == null ? new IllegalStateException("Host unavailable") : last;
        }

        private JSONObject readConfig() throws Exception {
            int length = input.readInt();
            if (length <= 0 || length > 65536) throw new IllegalArgumentException("Invalid configuration length");
            byte[] data = new byte[length];
            input.readFully(data);
            return new JSONObject(new String(data, StandardCharsets.UTF_8));
        }

        private int sendCommand(int command, byte[] payload) throws Exception {
            return sendCommand(command, payload, true);
        }

        private int sendCommand(int command, byte[] payload, boolean emitWriteEvent) throws Exception {
            String account = "admin";
            String commandPassword = password;
            if (encrypted) {
                account = noncePrefix + nonce(8);
                commandPassword = derivedPassword(account, password);
            }
            short number = ++commandNumber;
            byte[] body = new byte[40 + payload.length];
            putShort(body, 0, command);
            putShort(body, 2, number & 0xffff);
            putShort(body, 4, 0);
            putShort(body, 6, payload.length);
            byte[] auth = (account + "," + commandPassword).getBytes(StandardCharsets.US_ASCII);
            if (auth.length > 32) throw new IllegalArgumentException("Authentication header too long");
            System.arraycopy(auth, 0, body, 8, auth.length);
            System.arraycopy(payload, 0, body, 40, payload.length);
            Arrays.fill(auth, (byte) 0);

            byte[] unit = new byte[8 + body.length];
            unit[0] = tnpApplicationVersion;
            unit[1] = 3;
            putInt(unit, 4, body.length);
            System.arraycopy(body, 0, unit, 8, body.length);
            long started = System.nanoTime();
            int result = PPPP_APIs.PPPP_Write(handle, (byte) 0, unit, unit.length);
            long elapsedMicros = (System.nanoTime() - started) / 1_000L;
            if (emitWriteEvent) {
                JSONObject write = new JSONObject();
                write.put("returnValue", result);
                write.put("elapsedMicros", elapsedMicros);
                write.put("channel", 0);
                write.put("bufferLength", unit.length);
                write.put("command", command);
                write.put("commandNumber", number & 0xffff);
                write.put("tnpApplicationVersion", tnpApplicationVersion & 0xff);
                event("PPPP_Write", write);
            }
            Arrays.fill(body, (byte) 0);
            Arrays.fill(unit, (byte) 0);
            if (result < 0) throw new IllegalStateException("PPPP write failed");
            return number & 0xffff;
        }

        private CommandResponse readCommandResponse() throws Exception {
            byte[] unit = readUnit((byte) 0);
            if (unit.length < 48 || unit[1] != 3) throw new IllegalStateException("Invalid command response framing");
            int dataSize = getInt(unit, 4);
            if (dataSize + 8 != unit.length) throw new IllegalStateException("Invalid command response size");
            return new CommandResponse(unit[0], getUnsignedShort(unit, 8), getUnsignedShort(unit, 10), getInt(unit, 16));
        }

        private byte[] readUnit(byte channel) throws Exception {
            byte[] header = new byte[8];
            readExact(channel, header, "header");
            int dataSize = getInt(header, 4);
            if (dataSize < 0 || dataSize > 2 * 1024 * 1024) throw new IllegalStateException("Invalid TNP data size");
            byte[] body = new byte[dataSize];
            readExact(channel, body, "payload");
            ByteArrayOutputStream unit = new ByteArrayOutputStream(8 + dataSize);
            unit.write(header);
            unit.write(body);
            return unit.toByteArray();
        }

        private void readExact(byte channel, byte[] target, String phase) throws Exception {
            int[] size = new int[] {target.length};
            long started = System.nanoTime();
            int result = PPPP_APIs.PPPP_Read(handle, channel, target, size, -1);
            JSONObject read = callResult(result, started);
            read.put("channel", channel & 0xff);
            read.put("phase", phase);
            read.put("requestedLength", target.length);
            read.put("actualLength", size[0]);
            event("PPPP_Read", read);
            if (result < 0 || size[0] != target.length) throw new IllegalStateException("PPPP read failed");
        }

        private void readFrames(byte channel) {
            while (reading.get()) {
                try {
                    byte[] unit = readUnit(channel);
                    if (unit.length < 32 || unit[1] != 1 || getInt(unit, 4) + 8 != unit.length) {
                        throw new IllegalStateException("Invalid video frame framing");
                    }
                    if (channel == 2 && (unit[10] & 1) == 1) firstIFrameAt.compareAndSet(0, System.nanoTime());
                    frame(channel, unit);
                } catch (Throwable failure) {
                    if (reading.get()) safeError(failure);
                    return;
                }
            }
        }

        private String nonce(int length) {
            char[] value = new char[length];
            for (int index = 0; index < length; index++) value[index] = NONCE[random.nextInt(NONCE.length)];
            return new String(value);
        }

        private static String derivedPassword(String nonce, String key) throws Exception {
            Mac mac = Mac.getInstance("HmacSHA1");
            mac.init(new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8), "HmacSHA1"));
            byte[] digest = mac.doFinal(("user=xiaoyiuser&nonce=" + nonce).getBytes(StandardCharsets.UTF_8));
            String encoded = Base64.encodeToString(digest, Base64.NO_WRAP);
            Arrays.fill(digest, (byte) 0);
            return encoded.substring(0, Math.min(15, encoded.length()));
        }

        private synchronized void event(String name, JSONObject fields) throws Exception {
            if (output == null) return;
            fields.put("event", name);
            fields.put("timestampNanos", System.nanoTime());
            byte[] payload = fields.toString().getBytes(StandardCharsets.UTF_8);
            output.writeInt(payload.length + 1);
            output.writeByte(1);
            output.write(payload);
            output.flush();
        }

        private synchronized void frame(byte channel, byte[] unit) throws Exception {
            output.writeInt(1 + 1 + 8 + 4 + unit.length);
            output.writeByte(2);
            output.writeByte(channel);
            output.writeLong(System.nanoTime());
            output.writeInt(unit.length);
            output.write(unit);
            output.flush();
        }

        private void safeError(Throwable failure) {
            try {
                event("oracle_error", new JSONObject().put("exceptionType", failure.getClass().getSimpleName()));
            } catch (Throwable ignored) {}
        }

        private void clearSecrets() {
            did = null;
            password = null;
            noncePrefix = null;
        }

        private static String required(JSONObject value, String key) throws Exception {
            String result = value.getString(key);
            if (result.isEmpty()) throw new IllegalArgumentException("Missing required configuration field");
            return result;
        }

        private static JSONObject callResult(int result, long started) throws Exception {
            return new JSONObject().put("returnValue", result).put("elapsedMillis", (System.nanoTime() - started) / 1_000_000L);
        }

        private static void putShort(byte[] data, int offset, int value) {
            data[offset] = (byte) (value >>> 8);
            data[offset + 1] = (byte) value;
        }

        private static int getUnsignedShort(byte[] data, int offset) {
            return ((data[offset] & 0xff) << 8) | (data[offset + 1] & 0xff);
        }

        private static void putInt(byte[] data, int offset, int value) {
            data[offset] = (byte) (value >>> 24);
            data[offset + 1] = (byte) (value >>> 16);
            data[offset + 2] = (byte) (value >>> 8);
            data[offset + 3] = (byte) value;
        }

        private static int getInt(byte[] data, int offset) {
            return ((data[offset] & 0xff) << 24) | ((data[offset + 1] & 0xff) << 16)
                    | ((data[offset + 2] & 0xff) << 8) | (data[offset + 3] & 0xff);
        }

        private static final class CommandResponse {
            final byte version;
            final int commandType;
            final int commandNumber;
            final int authResult;

            CommandResponse(byte version, int commandType, int commandNumber, int authResult) {
                this.version = version;
                this.commandType = commandType;
                this.commandNumber = commandNumber;
                this.authResult = authResult;
            }
        }
    }
}
