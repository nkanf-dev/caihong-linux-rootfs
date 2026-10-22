package cn.armada.dualswitch;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
public final class ProcessSessionTest {
 static int assertions;
 static void require(boolean b,String message){assertions++;if(!b)throw new AssertionError(message);}
 static final class Pipe extends InputStream {
  final ByteArrayInputStream data;boolean closed;boolean fail;
  Pipe(String text){data=new ByteArrayInputStream(text.getBytes(StandardCharsets.UTF_8));}
  public int available()throws IOException{if(fail)throw new IOException("read failed");return data.available();}
  public int read(){throw new AssertionError("blocking read() must not be used");}
  public int read(byte[] b,int o,int n){return data.read(b,o,n);}
  public void close(){closed=true;}
 }
 static final class Input extends ByteArrayOutputStream {boolean closed;public void close(){closed=true;}}
 static final class FakeProcess extends Process {
  final Pipe out,err;final Input input=new Input();boolean alive=true,destroyed,timeout,interrupt;
  FakeProcess(String out,String err){this.out=new Pipe(out);this.err=new Pipe(err);}
  public OutputStream getOutputStream(){return input;}
  public InputStream getInputStream(){return out;}
  public InputStream getErrorStream(){return err;}
  public int waitFor(){alive=false;return 0;}
  public boolean waitFor(long time,TimeUnit unit)throws InterruptedException{
   if(interrupt)throw new InterruptedException("interrupted");if(timeout)return false;alive=false;return true;
  }
  public int exitValue(){return 0;}
  public boolean isAlive(){return alive;}
  public void destroy(){destroyed=true;alive=false;}
  public Process destroyForcibly(){destroy();return this;}
 }
 static final class ObservedProcess extends Process {
  final Process child;final CountDownLatch waiting=new CountDownLatch(1);
  ObservedProcess(Process child){this.child=child;}
  public OutputStream getOutputStream(){return child.getOutputStream();}
  public InputStream getInputStream(){return child.getInputStream();}
  public InputStream getErrorStream(){return child.getErrorStream();}
  public int waitFor()throws InterruptedException{return child.waitFor();}
  public boolean waitFor(long time,TimeUnit unit)throws InterruptedException{waiting.countDown();return child.waitFor(time,unit);}
  public int exitValue(){return child.exitValue();}
  public boolean isAlive(){return child.isAlive();}
  public void destroy(){child.destroy();}
  public Process destroyForcibly(){child.destroyForcibly();return this;}
 }
 static void cleaned(FakeProcess p){
  require(p.input.closed && p.out.closed && p.err.closed,"all process streams closed");
  require(!p.alive,"su is no longer alive");
  for(Thread t:Thread.getAllStackTraces().keySet())
   require(!t.isAlive() || (!t.getName().equals("Armada-stdout") && !t.getName().equals("Armada-stderr")),"drain threads stopped");
 }
 public static void main(String[] args)throws Exception{
  if(args.length>0 && args[0].equals("child")){
   if(System.in.read()!=71)System.exit(3);
   System.out.print("{\"native\":true}");System.out.flush();
   if(args.length>1 && args[1].equals("hold"))while(System.in.read()!=-1){}
   return;
  }
  FakeProcess p=new FakeProcess("{\"ok\":true}","warning");
  ProcessSession.Result r=ProcessSession.execute(p,100);
  require(r.out.equals("{\"ok\":true}") && r.err.equals("warning"),"bounded output retained");
  require(p.input.toByteArray().length==1 && p.input.toByteArray()[0]==71,"managed start token written");cleaned(p);
  p=new FakeProcess("","");p.timeout=true;boolean timedOut=false;
  try{ProcessSession.execute(p,1);}catch(IOException e){timedOut=true;}
  require(timedOut && p.destroyed,"timeout kills su");cleaned(p);
  p=new FakeProcess("","");p.interrupt=true;boolean interrupted=false;
  try{ProcessSession.execute(p,1);}catch(InterruptedException e){interrupted=true;}
  require(interrupted && p.destroyed,"interrupted wait kills su");cleaned(p);
  p=new FakeProcess(new String(new char[70000]).replace('\0','x'),"");boolean overflow=false;
  try{ProcessSession.execute(p,100);}catch(IOException e){overflow=true;}
  require(overflow,"oversize output rejected");cleaned(p);
  String java=new File(System.getProperty("java.home"),"bin/java").getPath();
  Process nativeChild=new ProcessBuilder(java,"-cp",System.getProperty("java.class.path"),ProcessSessionTest.class.getName(),"child").start();
  r=ProcessSession.execute(nativeChild,2000);
  require(r.exit==0 && r.out.equals("{\"native\":true}"),"native process output and handshake");
  nativeChild=new ProcessBuilder(java,"-cp",System.getProperty("java.class.path"),ProcessSessionTest.class.getName(),"child","hold").start();
  boolean nativeTimeout=false;try{ProcessSession.execute(nativeChild,100);}catch(IOException e){nativeTimeout=true;}
  require(nativeTimeout,"native waiting child times out");
  require(nativeChild.waitFor(2,TimeUnit.SECONDS),"native process terminated after timeout");
  Process interruptedChild=new ProcessBuilder(java,"-cp",System.getProperty("java.class.path"),ProcessSessionTest.class.getName(),"child","hold").start();
  ObservedProcess observed=new ObservedProcess(interruptedChild);
  ExecutorService owner=Executors.newSingleThreadExecutor();
  try{
   Future<Boolean> interruptedResult=owner.submit(()->{
    try{ProcessSession.execute(observed,5000);return false;}catch(InterruptedException e){return true;}
   });
   require(observed.waiting.await(2,TimeUnit.SECONDS),"native root session reached process wait");
   owner.shutdownNow();
   require(interruptedResult.get(2,TimeUnit.SECONDS),"owner shutdownNow interrupts active native session");
   require(owner.awaitTermination(2,TimeUnit.SECONDS),"interrupted session worker stops");
   require(interruptedChild.waitFor(2,TimeUnit.SECONDS),"interrupted native child terminated");
   boolean drainsStopped=true;
   for(Thread t:Thread.getAllStackTraces().keySet())
    if(t.isAlive() && (t.getName().equals("Armada-stdout") || t.getName().equals("Armada-stderr")))drainsStopped=false;
   require(drainsStopped,"interrupted native session leaves no drain threads");
  }finally{
   owner.shutdownNow();interruptedChild.destroyForcibly();
  }
  System.out.println("ProcessSessionTest: PASS ("+assertions+" assertions)");
 }
}
