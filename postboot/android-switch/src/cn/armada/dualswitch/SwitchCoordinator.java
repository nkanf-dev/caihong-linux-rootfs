package cn.armada.dualswitch;

import java.util.List;

/** Pure policy and operation ordering. Android I/O is supplied by the helper. */
final class SwitchCoordinator {
    interface Backend {
        void checkDeadline() throws Exception;
        Policy.Status inspect() throws Exception;
        int current() throws Exception;
        int active() throws Exception;
        int merge() throws Exception;
        String propertySuffix() throws Exception;
        boolean targetBootable() throws Exception;
        void setTargetActive() throws Exception;
        void reboot() throws Exception;
    }
    static void run(Backend b) throws Exception {
        b.checkDeadline();
        Policy.Status s = b.inspect();
        List<String> blockers = Policy.blockers(s);
        if (!blockers.isEmpty()) throw new Exception(String.join("；",blockers));
        if (b.current() != TargetConfig.ANDROID_SLOT || b.active() != TargetConfig.ANDROID_SLOT
                || b.merge() != s.merge || !"_a".equals(b.propertySuffix()))
            throw new Exception("启动状态已改变，请重新检查");
        b.checkDeadline();
        b.setTargetActive();
        if (b.active() != TargetConfig.LINUX_SLOT || !b.targetBootable())
            throw new Exception("下次启动槽读回校验失败，已停止重启");
        if (b.current() != TargetConfig.ANDROID_SLOT)
            throw new Exception("当前槽读回异常，已停止重启");
        b.checkDeadline();
        b.reboot();
    }
}
