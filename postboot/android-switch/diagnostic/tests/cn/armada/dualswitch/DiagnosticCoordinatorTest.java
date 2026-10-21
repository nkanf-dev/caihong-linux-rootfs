package cn.armada.dualswitch;
public final class DiagnosticCoordinatorTest {
 static int assertions;
 static void check(boolean b,String message){assertions++;if(!b)throw new AssertionError(message);}
 static final class Fake implements DiagnosticCoordinator.Backend {
  Policy.Status before=PolicyTest.valid(),after=PolicyTest.valid();
  int checks,writes;boolean expire,changed,failWrite,failAfter;
  public void checkDeadline()throws Exception{checks++;if(expire)throw new Exception("expired");}
  public Policy.Status inspect(){return before;}
  public void refreshHal(Policy.Status s){if(changed)s.active=1;}
  public void setActiveB()throws Exception{writes++;if(failWrite)throw new Exception("HAL failure");}
  public Policy.Status readAfter()throws Exception{if(failAfter)throw new Exception("read failed");after.active=1;return after;}
 }
 public static void main(String[] args){
  Fake f=new Fake();DiagnosticCoordinator.Result r=DiagnosticCoordinator.select(f);
  check(r.completed && r.attempted && f.writes==1 && r.after.active==1,"one selection with before/after");
  f=new Fake();f.before.hashMatches=false;r=DiagnosticCoordinator.select(f);check(f.writes==0&&!r.attempted,"hash blocks write");
  f=new Fake();f.before.linuxBytes--;r=DiagnosticCoordinator.select(f);check(f.writes==0,"64GiB required");
  f=new Fake();f.before.merge=4;r=DiagnosticCoordinator.select(f);check(f.writes==0,"merge0 only");
  f=new Fake();f.before.current=1;r=DiagnosticCoordinator.select(f);check(f.writes==0,"currenta required");
  f=new Fake();f.before.active=1;r=DiagnosticCoordinator.select(f);check(f.writes==0,"activea required");
  f=new Fake();f.before.bootableA=false;r=DiagnosticCoordinator.select(f);check(f.writes==0,"Android fallback required");
  f=new Fake();f.changed=true;r=DiagnosticCoordinator.select(f);check(f.writes==0,"refreshed HAL must still pass");
  f=new Fake();f.expire=true;r=DiagnosticCoordinator.select(f);check(f.writes==0,"monotonic deadline required");
  f=new Fake();f.failWrite=true;r=DiagnosticCoordinator.select(f);check(r.attempted&&!r.completed&&r.after!=null,"exception still gathers after snapshot");
  f=new Fake();f.failAfter=true;r=DiagnosticCoordinator.select(f);check(r.completed&&!r.afterError.isEmpty(),"after failure is explicit");
  System.out.println("DiagnosticCoordinatorTest: PASS ("+assertions+" assertions)");
 }
}
