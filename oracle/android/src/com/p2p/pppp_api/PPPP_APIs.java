package com.p2p.pppp_api;

import com.tnp.model.st_PPPP_Session;

public final class PPPP_APIs {
    static {
        System.loadLibrary("PPPP_API");
    }

    private PPPP_APIs() {}

    public static native int PPPP_Initialize(byte[] initString, int maxSessions);
    public static native int PPPP_DeInitialize();
    public static native int PPPP_GetAPIVersion();
    public static native int PPPP_Config_Debug(byte enabled, int level);
    public static native int PPPP_Connect(String did, byte flag, int udpPort, String server, String deviceKey);
    public static native int PPPP_WakeUp_And_Connect(String did, byte flag, int udpPort, String server, String deviceKey);
    public static native int PPPP_Connect_Break(String did);
    public static native int PPPP_Check(int handle, st_PPPP_Session session);
    public static native int PPPP_Read(int handle, byte channel, byte[] data, int[] size, int timeout);
    public static native int PPPP_Write(int handle, byte channel, byte[] data, int size);
    public static native int PPPP_ForceClose(int handle);

    public void onIncomingConnectionCallback() {}
    public void onR2PMPCallback(int value) {}
}
