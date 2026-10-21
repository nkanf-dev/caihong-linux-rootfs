package android.os;
public final class ServiceManager {
 public static IBinder service;
 public static IBinder getService(String name) {
  if (!name.equals("android.hardware.boot.IBootControl/default"))throw new AssertionError("service name");
  return service;
 }
}
