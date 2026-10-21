package cn.armada.dualswitch;
import java.util.*;
public final class SwitchCoordinatorTest {
    static int assertions;
    static void require(boolean p,String message) { assertions++; if(!p)throw new AssertionError(message); }
    static class Fake implements SwitchCoordinator.Backend {
        Policy.Status status=PolicyTest.valid();
        int cur=0, next=0, merge=0, writes, reboots;
        boolean canBoot=true, wrongReadback, failSet, failReboot, badCurrentAfter, failActiveAfter;
        String suffix="_a";
        int deadlineChecks, expireOnCheck;
        public void checkDeadline() throws Exception { deadlineChecks++; if(deadlineChecks==expireOnCheck)throw new Exception("expired"); }
        public Policy.Status inspect() { return status; }
        public int current() { return writes>0 && badCurrentAfter ? 1 : cur; }
        public int active() throws Exception { if(writes>0 && failActiveAfter)throw new Exception("binder died"); return next; }
        public int merge() { return merge; }
        public String propertySuffix() { return suffix; }
        public boolean targetBootable() { return canBoot; }
        public void setTargetActive() throws Exception { writes++; if(failSet)throw new Exception("HAL rejected write"); if(!wrongReadback)next=1; }
        public void reboot() throws Exception { reboots++; if(failReboot)throw new Exception("reboot denied"); }
    }
    static void fails(Fake f,String message) throws Exception {
        boolean rejected=false;try{SwitchCoordinator.run(f);}catch(Exception e){rejected=true;}
        require(rejected,message);
    }
    public static void main(String[] args) throws Exception {
        Fake f=new Fake();SwitchCoordinator.run(f);require(f.writes==1 && f.reboots==1,"one verified write then reboot");
        f=new Fake();f.status.hashMatches=false;fails(f,"digest mismatch rejected");require(f.writes==0 && f.reboots==0,"digest mismatch has no write/reboot");
        f=new Fake();f.status.deploymentReady=false;fails(f,"undeployed rejected");require(f.writes==0 && f.reboots==0,"undeployed has no write/reboot");
        f=new Fake();f.cur=1;fails(f,"current changed");require(f.writes==0,"current mismatch has no write");
        f=new Fake();f.next=1;fails(f,"next changed");require(f.writes==0,"next mismatch has no write");
        f=new Fake();f.merge=3;fails(f,"merge changed");require(f.writes==0,"merge mismatch has no write");
        f=new Fake();f.suffix="_b";fails(f,"property changed");require(f.writes==0,"property mismatch has no write");
        f=new Fake();f.failSet=true;fails(f,"HAL write failure");require(f.writes==1 && f.reboots==0,"HAL write failure stops reboot");
        f=new Fake();f.wrongReadback=true;fails(f,"active readback mismatch");require(f.writes==1 && f.reboots==0,"bad readback stops reboot");
        f=new Fake();f.canBoot=false;fails(f,"target not bootable");require(f.reboots==0,"bootable check stops reboot");
        f=new Fake();f.badCurrentAfter=true;fails(f,"current cannot change before reboot");require(f.reboots==0,"bad current readback stops reboot");
        f=new Fake();f.failActiveAfter=true;fails(f,"binder failure after write");require(f.reboots==0,"binder failure stops reboot");
        f=new Fake();f.failReboot=true;fails(f,"reboot failure reported");require(f.writes==1 && f.reboots==1,"reboot attempted only after verified write");
        f=new Fake();f.expireOnCheck=1;fails(f,"authorization arrived too late");require(f.writes==0 && f.reboots==0,"late authorization cannot write");
        f=new Fake();f.expireOnCheck=2;fails(f,"inspection took too long");require(f.writes==0 && f.reboots==0,"expired inspection cannot write");
        f=new Fake();f.expireOnCheck=3;fails(f,"HAL verification took too long");require(f.writes==1 && f.reboots==0,"expired after write stops reboot");
        System.out.println("SwitchCoordinatorTest: PASS ("+assertions+" assertions)");
    }
}
