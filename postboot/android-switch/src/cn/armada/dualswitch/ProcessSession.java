package cn.armada.dualswitch;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

/** Owns all app-side process streams and drain threads. */
final class ProcessSession {
    static final class Result {
        final int exit;
        final String out,err;
        Result(int exit,String out,String err){this.exit=exit;this.out=out;this.err=err;}
    }
    private static final class Drain extends Thread {
        final InputStream in;
        final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        volatile boolean stopping,overflow;
        volatile IOException error;
        Drain(InputStream in,String name){super(name);this.in=in;setDaemon(true);}
        private boolean readAvailable() throws IOException {
            int available=in.available();
            if(available<=0)return false;
            byte[] buffer=new byte[Math.min(available,4096)];
            int n=in.read(buffer);
            if(n<=0)return false;
            int retain=Math.min(n,65536-bytes.size());
            if(retain>0)bytes.write(buffer,0,retain);
            if(retain!=n)overflow=true;
            return true;
        }
        public void run(){
            try {
                while(!stopping){
                    if(!readAvailable()){
                        synchronized(this){if(!stopping)wait(20L);}
                    }
                }
                while(readAvailable()){}
            }catch(InterruptedException e){Thread.currentThread().interrupt();}
            catch(IOException e){if(!stopping)error=e;}
        }
        void stopDrain(){stopping=true;synchronized(this){notifyAll();}}
        String text(){return new String(bytes.toByteArray(),StandardCharsets.UTF_8).trim();}
    }
    private static void close(Closeable stream){try{stream.close();}catch(IOException ignored){}}
    private static void stop(Drain drain) {
        drain.stopDrain();
        try{drain.join(2000L);}catch(InterruptedException e){Thread.currentThread().interrupt();}
        close(drain.in);
        if(drain.isAlive()){
            drain.interrupt();
            try{drain.join(200L);}catch(InterruptedException e){Thread.currentThread().interrupt();}
        }
    }
    static Result execute(Process p,long timeoutMillis)throws Exception{
        Drain out=new Drain(p.getInputStream(),"Armada-stdout");
        Drain err=new Drain(p.getErrorStream(),"Armada-stderr");
        out.start();err.start();
        try{
            p.getOutputStream().write(71);p.getOutputStream().flush();
            if(!p.waitFor(timeoutMillis,TimeUnit.MILLISECONDS))
                throw new IOException("root 操作超时，请重新检查下次启动槽");
            out.stopDrain();err.stopDrain();out.join(2000L);err.join(2000L);
            if(out.isAlive() || err.isAlive() || out.overflow || err.overflow)
                throw new IOException("root 返回内容异常，请重新检查");
            if(out.error!=null)throw out.error;
            if(err.error!=null)throw err.error;
            return new Result(p.exitValue(),out.text(),err.text());
        }finally{
            // EOF cancels an app-originated helper, including one authorized after timeout.
            close(p.getOutputStream());
            if(p.isAlive())p.destroyForcibly();
            stop(out);stop(err);
            close(p.getInputStream());close(p.getErrorStream());
            if(p.isAlive())p.destroyForcibly();
        }
    }
}
