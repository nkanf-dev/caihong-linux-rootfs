package cn.armada.dualswitch;
import java.util.*;
public final class PolicyTest {
    static int assertions;
    static void require(boolean p, String message) { assertions++; if(!p)throw new AssertionError(message); }
    static Policy.Status valid() {
        Policy.Status s=new Policy.Status();
        s.root=true; s.model=TargetConfig.MODEL; s.device=TargetConfig.DEVICE; s.halVerified=true;
        s.slots=2; s.suffixA="_a"; s.suffixB="_b"; s.current=0; s.active=0;
        s.propSuffix="_a"; s.bootableA=true; s.bootableB=true; s.merge=0; s.linuxBlock=true;
        s.partlabel=TargetConfig.LINUX_PARTLABEL; s.linuxBytes=TargetConfig.LINUX_BYTES;
        s.bootBlock=true; s.bootIdentityVerified=true; s.bootPartlabel="boot_b"; s.deploymentReady=true; s.hashMatches=true; return s;
    }
    static void blocked(Policy.Status s, String message) { require(!Policy.blockers(s).isEmpty(),message); }
    public static void main(String[] a) {
        require(Policy.blockers(valid()).isEmpty(),"valid Android a deployment is allowed");
        Policy.Status s=valid(); s.root=false; blocked(s,"root required");
        s=valid(); s.model="OPD2403"; blocked(s,"exact model required");
        s=valid(); s.device="unknown"; blocked(s,"exact device required");
        s=valid(); s.halVerified=false; blocked(s,"AIDL identity required");
        s=valid(); s.current=1; blocked(s,"Android must run a");
        s=valid(); s.active=1; blocked(s,"pending boot changes rejected");
        s=valid(); s.slots=3; blocked(s,"two slots required");
        s=valid(); s.suffixB="_a"; blocked(s,"slot mapping required");
        s=valid(); s.propSuffix="_b"; blocked(s,"property must match current slot");
        s=valid(); s.bootableA=false; blocked(s,"Android fallback must remain bootable");
        for(int merge: new int[]{-1,1,2,3,4,5}) { s=valid();s.merge=merge;blocked(s,"unsafe merge status "+merge); }
        s=valid(); s.linuxBlock=false; blocked(s,"linux must be a block device");
        s=valid(); s.linuxBytes--; blocked(s,"linux must be exactly 64 GiB");
        s=valid(); s.partlabel="userdata"; blocked(s,"linux GPT label required");
        s=valid(); s.bootBlock=false; blocked(s,"boot_b must be block device");
        s=valid(); s.bootIdentityVerified=false; blocked(s,"canonical boot identity required");
        s=valid(); s.bootPartlabel="boot_a"; blocked(s,"actual boot_b partlabel required");
        s=valid(); s.deploymentReady=false; blocked(s,"explicit deployed config required");
        s=valid(); s.hashMatches=false; blocked(s,"boot_b image digest required");
        s=valid(); s.error="permission denied"; blocked(s,"probe errors block write");
        require(Policy.validDigest(String.join("", Collections.nCopies(64,"a"))),"64 lowercase hex accepted");
        require(!Policy.validDigest(""),"empty digest rejected");
        require(!Policy.validDigest(String.join("",Collections.nCopies(64,"G"))),"nonhex digest rejected");
        require(!Policy.validDigest(null),"null digest rejected");
        require(Policy.quote("/data/app/a'b.apk").equals("'/data/app/a'\\''b.apk'"),"shell apostrophe escaped");
        System.out.println("PolicyTest: PASS ("+assertions+" assertions)");
    }
}
