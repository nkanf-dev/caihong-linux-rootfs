package cn.armada.dualswitch;

import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.*;

/** Root-only app_process entry point. status is read-only; switch requires a fixed confirmation token. */
public final class BootControlHelper {
    private static final String TOKEN = "CONFIRM_ANDROID_A_TO_ARMADA_B";
    private static boolean slotWriteAttempted;
    static String property(String name) throws Exception {
        return (String) Class.forName("android.os.SystemProperties")
            .getMethod("get", String.class).invoke(null, name);
    }
    private static String text(File f) throws Exception {
        return new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8).trim();
    }
    private static boolean block(File f) {
        try { return OsConstants.S_ISBLK(Os.stat(f.getPath()).st_mode); }
        catch (Exception e) { return false; }
    }
    static Policy.Status inspect() {
        Policy.Status s = new Policy.Status();
        s.root = Os.getuid() == 0;
        if (!s.root) { s.error = "helper 需要 root 权限"; return s; }
        try {
            s.model = property("ro.product.model");
            s.device = property("ro.product.device");
            s.propSuffix = property("ro.boot.slot_suffix");
            File linux = new File(TargetConfig.LINUX_PATH).getCanonicalFile();
            s.linuxBlock = block(linux);
            if (s.linuxBlock) {
                File sys = new File("/sys/class/block", linux.getName());
                s.linuxBytes = Math.multiplyExact(Long.parseLong(text(new File(sys, "size"))), 512L);
                for (String line : text(new File(sys, "uevent")).split("\n"))
                    if (line.startsWith("PARTNAME=")) s.partlabel = line.substring(9);
            }
            File boot = new File(TargetConfig.BOOT_PATH).getCanonicalFile();
            s.bootBlock = block(boot);
            s.bootCanonical = boot.getPath();
            if (s.bootBlock) {
                File sys = new File("/sys/class/block",boot.getName());
                String uevent = text(new File(sys,"uevent"));
                s.bootPartlabel = BlockIdentity.partname(uevent);
                BlockIdentity.requireBootB(boot.getPath(),uevent,text(new File(sys,"dev")),Os.stat(boot.getPath()).st_rdev);
                s.bootIdentityVerified = true;
            }
            s.deploymentReady = TargetConfig.DEPLOYMENT_READY
                && TargetConfig.IMAGE_BYTES > 0 && Policy.validDigest(TargetConfig.IMAGE_SHA256);
            if (s.bootBlock && s.bootIdentityVerified && TargetConfig.IMAGE_BYTES > 0 && Policy.validDigest(TargetConfig.IMAGE_SHA256)) {
                s.bootHash = ImageDigest.prefix(boot, TargetConfig.IMAGE_BYTES);
                s.hashMatches = s.bootHash.equals(TargetConfig.IMAGE_SHA256);
            }
        } catch (Exception e) { s.error = "分区或设备检查失败：" + brief(e); }
        try {
            BootControlClient c = new BootControlClient();
            s.halVerified = true;
            s.slots = c.integer(BootControlClient.GET_SLOTS, null);
            s.current = c.integer(BootControlClient.GET_CURRENT, null);
            s.active = c.integer(BootControlClient.GET_ACTIVE, null);
            s.merge = c.integer(BootControlClient.GET_MERGE, null);
            s.suffixA = c.string(BootControlClient.GET_SUFFIX, 0);
            s.suffixB = c.string(BootControlClient.GET_SUFFIX, 1);
            s.bootableA = c.bootable(0);
            s.bootableB = c.bootable(1);
        } catch (Exception e) { s.error += (s.error.isEmpty() ? "" : "；") + "启动接口检查失败：" + brief(e); }
        return s;
    }
    private static String brief(Throwable e) {
        while (e.getCause() != null) e = e.getCause();
        String message = e.getMessage();
        return e.getClass().getSimpleName() + (message == null ? "" : ": " + message);
    }
    private static JSONObject json(Policy.Status s) throws Exception {
        JSONObject j = new JSONObject();
        j.put("protocol",1); j.put("root",s.root); j.put("model",s.model); j.put("device",s.device);
        j.put("halVerified",s.halVerified); j.put("aidlVersion",TargetConfig.AIDL_VERSION);
        j.put("aidlHash",TargetConfig.AIDL_HASH); j.put("current",s.current); j.put("active",s.active);
        j.put("slots",s.slots); j.put("propSuffix",s.propSuffix); j.put("suffixA",s.suffixA);
        j.put("suffixB",s.suffixB); j.put("merge",s.merge); j.put("bootableA",s.bootableA);
        j.put("bootableB",s.bootableB); j.put("linuxBlock",s.linuxBlock); j.put("partlabel",s.partlabel);
        j.put("linuxBytes",s.linuxBytes); j.put("bootBlock",s.bootBlock); j.put("bootHash",s.bootHash);
        j.put("bootIdentityVerified",s.bootIdentityVerified); j.put("bootCanonical",s.bootCanonical);
        j.put("bootPartlabel",s.bootPartlabel);
        j.put("deploymentReady",s.deploymentReady); j.put("hashMatches",s.hashMatches);
        j.put("error",s.error); j.put("ready",Policy.blockers(s).isEmpty());
        j.put("blockers",new org.json.JSONArray(Policy.blockers(s)));
        return j;
    }
    private static void emit(JSONObject j) { System.out.println(j.toString()); System.out.flush(); }
    public static void main(String[] args) {
        boolean managed=args.length>0 && "--managed".equals(args[args.length-1]);
        final InputGuard guard=managed ? new InputGuard(System.in,() -> System.exit(125)) : null;
        if(managed){
            try{if(System.in.read()!=71)System.exit(125);}catch(IOException e){System.exit(125);}
            args=Arrays.copyOf(args,args.length-1);guard.start();
        }
        Timer timer = new Timer(true);
        timer.schedule(new TimerTask() { public void run() {
            System.err.println("检查超时；请重新检查下次启动槽"); System.exit(124);
        }}, 120_000L);
        try {
            if (args.length == 1 && "status".equals(args[0])) {
                emit(json(inspect())); return;
            }
            if (args.length != 3 || !"switch".equals(args[0]) || !TOKEN.equals(args[1]))
                throw new Exception("命令参数无效");
            final long deadline = Long.parseLong(args[2]);
            SwitchCoordinator.run(new SwitchCoordinator.Backend() {
                BootControlClient client;
                private BootControlClient client() throws Exception {
                    if (client == null) client = new BootControlClient();
                    return client;
                }
                public void checkDeadline() throws Exception {
                    if(guard!=null)guard.requireActive();
                    SwitchDeadline.check(android.os.SystemClock.elapsedRealtime(),deadline);
                }
                public Policy.Status inspect() { return BootControlHelper.inspect(); }
                public int current() throws Exception { return client().integer(BootControlClient.GET_CURRENT,null); }
                public int active() throws Exception { return client().integer(BootControlClient.GET_ACTIVE,null); }
                public int merge() throws Exception { return client().integer(BootControlClient.GET_MERGE,null); }
                public String propertySuffix() throws Exception { return property("ro.boot.slot_suffix"); }
                public boolean targetBootable() throws Exception { return client().bootable(TargetConfig.LINUX_SLOT); }
                public void setTargetActive() throws Exception {
                    slotWriteAttempted = true;
                    client().setActive(TargetConfig.LINUX_SLOT);
                }
                public void reboot() throws Exception {
                    Process reboot = new ProcessBuilder("/system/bin/reboot").inheritIO().start();
                    int exit = reboot.waitFor();
                    if (exit != 0) throw new Exception("重启命令失败，退出码 " + exit);
                    JSONObject result = new JSONObject(); result.put("protocol",1);
                    result.put("switchVerified",true); result.put("nextSlot",TargetConfig.LINUX_SLOT);
                    result.put("message","下次启动槽已设为 b，正在重启"); emit(result);
                }
            });
        } catch (Throwable e) {
            try {
                JSONObject error = new JSONObject(); error.put("protocol",1); error.put("error",brief(e));
                error.put("slotWriteAttempted",slotWriteAttempted);
                error.put("message",slotWriteAttempted ? "已停止重启；下次启动槽可能已改为 b，请重新检查" : "已停止切换");
                emit(error);
            } catch (Exception ignored) { System.err.println(brief(e)); }
            System.exit(1);
        } finally { timer.cancel(); }
    }
}
