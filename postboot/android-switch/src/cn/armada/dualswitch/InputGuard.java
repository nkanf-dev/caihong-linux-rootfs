package cn.armada.dualswitch;

import java.io.InputStream;

/** A managed helper remains valid only while the app keeps its stdin pipe open. */
final class InputGuard extends Thread {
    private final InputStream input;
    private final Runnable onClosed;
    private volatile boolean cancelled;
    InputGuard(InputStream input,Runnable onClosed){super("Armada-parent-watch");this.input=input;this.onClosed=onClosed;setDaemon(true);}
    public void run(){
        try{while(input.read()!=-1){}}catch(Exception ignored){}
        cancelled=true;onClosed.run();
    }
    void requireActive()throws Exception{if(cancelled)throw new Exception("应用已结束此次请求");}
}
