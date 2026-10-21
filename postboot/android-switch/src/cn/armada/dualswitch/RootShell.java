package cn.armada.dualswitch;

final class RootShell {
    static ProcessSession.Result run(String apkPath,boolean switchSlot)throws Exception{
        long deadline=android.os.SystemClock.elapsedRealtime()+60_000L;
        String command="CLASSPATH="+Policy.quote(apkPath)
            +" exec /system/bin/app_process / cn.armada.dualswitch.BootControlHelper "
            +(switchSlot ? "switch CONFIRM_ANDROID_A_TO_ARMADA_B "+deadline+" --managed" : "status --managed");
        Process p=new ProcessBuilder("su","-c",command).start();
        return ProcessSession.execute(p,135_000L);
    }
}
