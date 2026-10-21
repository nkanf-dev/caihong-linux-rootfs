package cn.armada.dualswitch;
import java.io.*;
import java.util.concurrent.*;
public final class InputGuardTest {
 public static void main(String[] args)throws Exception{
  PipedInputStream input=new PipedInputStream();PipedOutputStream writer=new PipedOutputStream(input);
  CountDownLatch stopped=new CountDownLatch(1);
  InputGuard guard=new InputGuard(input,stopped::countDown);guard.start();
  guard.requireActive();writer.close();
  if(!stopped.await(2,TimeUnit.SECONDS))throw new AssertionError("EOF did not cancel helper");
  boolean rejected=false;try{guard.requireActive();}catch(Exception e){rejected=true;}
  if(!rejected)throw new AssertionError("closed managed request accepted");
  guard.join(1000);if(guard.isAlive())throw new AssertionError("stdin watcher leaked");input.close();
  System.out.println("InputGuardTest: PASS (4 assertions)");
 }
}
