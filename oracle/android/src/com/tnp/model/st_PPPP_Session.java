package com.tnp.model;

public final class st_PPPP_Session {
    int Skt = -1;
    byte[] RemoteIP = new byte[16];
    int RemotePort;
    byte[] MyLocalIP = new byte[16];
    int MyLocalPort;
    byte[] MyWanIP = new byte[16];
    int MyWanPort;
    int ConnectTime;
    int ConnectTimeP2P;
    int ConnectTimeRelay;
    byte[] DID = new byte[24];
    byte bCorD;
    byte bMode;

    public int getConnectTime() { return ConnectTime; }
    public int getConnectTimeP2P() { return ConnectTimeP2P; }
    public int getConnectTimeRelay() { return ConnectTimeRelay; }
    public int getMode() { return bMode & 0xff; }
}
