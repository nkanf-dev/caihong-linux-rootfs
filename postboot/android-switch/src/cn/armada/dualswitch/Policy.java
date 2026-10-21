package cn.armada.dualswitch;

import java.util.ArrayList;
import java.util.List;

public final class Policy {
    private Policy() {}
    public static final class Status {
        public boolean root, linuxBlock, bootBlock, halVerified, bootableA, bootableB;
        public boolean deploymentReady, hashMatches, bootIdentityVerified;
        public String model = "", device = "", propSuffix = "", suffixA = "", suffixB = "";
        public String partlabel = "", bootHash = "", error = "", bootCanonical = "", bootPartlabel = "";
        public long linuxBytes;
        public int current = -1, active = -1, slots = -1, merge = -1;
    }
    public static List<String> blockers(Status s) {
        List<String> b = new ArrayList<>();
        if (!s.root) b.add("请在 KernelSU 中授予 root 权限");
        if (!TargetConfig.MODEL.equals(s.model) || !TargetConfig.DEVICE.equals(s.device))
            b.add("设备型号或代号不匹配");
        if (!s.halVerified) b.add("启动 HAL 接口校验失败");
        if (s.slots != 2 || !"_a".equals(s.suffixA) || !"_b".equals(s.suffixB))
            b.add("A/B 槽位映射不匹配");
        if (s.current != TargetConfig.ANDROID_SLOT || !"_a".equals(s.propSuffix))
            b.add("请先从 Android 槽 a 启动");
        if (s.active != TargetConfig.ANDROID_SLOT) b.add("下次启动槽已不是 a，请先检查启动设置");
        if (!s.bootableA) b.add("Android 槽 a 未标记为可启动");
        if (s.merge != 0) b.add("系统更新快照状态不是 NONE");
        if (!s.linuxBlock || !TargetConfig.LINUX_PARTLABEL.equals(s.partlabel)
                || s.linuxBytes != TargetConfig.LINUX_BYTES)
            b.add("未找到配置的 64 GiB linux 分区");
        if (!s.bootBlock) b.add("未找到配置的 boot_b 块设备");
        if (!s.bootIdentityVerified || !"boot_b".equals(s.bootPartlabel)) b.add("boot_b 真实设备身份检查失败");
        if (!s.deploymentReady) b.add("请先完成 Armada 部署并更新应用配置");
        if (!s.hashMatches) b.add("boot_b 与配置的 Armada 镜像不匹配");
        if (!s.error.isEmpty()) b.add(s.error);
        return b;
    }
    public static boolean validDigest(String value) {
        return value != null && value.matches("[0-9a-f]{64}");
    }
    public static String quote(String s) {
        return "'" + s.replace("'", "'\\''") + "'";
    }
}
