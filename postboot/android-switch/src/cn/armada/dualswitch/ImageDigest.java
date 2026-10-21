package cn.armada.dualswitch;

import java.io.*;
import java.security.MessageDigest;
import java.util.Locale;

final class ImageDigest {
    private ImageDigest() {}
    static String prefix(File f, long bytes) throws Exception {
        if (bytes <= 0) throw new Exception("Armada 镜像长度未配置");
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[] buffer = new byte[1024 * 1024];
        try (InputStream in = new FileInputStream(f)) {
            long remaining = bytes;
            while (remaining > 0) {
                int n = in.read(buffer,0,(int)Math.min(buffer.length,remaining));
                if (n < 0) throw new EOFException("boot_b 长度不足");
                md.update(buffer,0,n); remaining -= n;
            }
        }
        StringBuilder result = new StringBuilder();
        for (byte b : md.digest()) result.append(String.format(Locale.ROOT,"%02x",b & 255));
        return result.toString();
    }
}
