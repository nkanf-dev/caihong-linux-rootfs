package cn.armada.dualswitch;
public final class BlockIdentityTest {
 static int assertions;
 static void require(boolean b,String message){assertions++;if(!b)throw new AssertionError(message);}
 static void reject(String path,String uevent,String dev,long rdev)throws Exception{
  boolean rejected=false;try{BlockIdentity.requireBootB(path,uevent,dev,rdev);}catch(Exception e){rejected=true;}
  require(rejected,"bad boot identity rejected");
 }
 public static void main(String[] args)throws Exception{
  long rdev=(259L<<8)|17;
  BlockIdentity.requireBootB("/dev/block/sde17","MAJOR=259\nMINOR=17\nPARTNAME=boot_b\n","259:17",rdev);assertions++;
  require(BlockIdentity.major(rdev)==259 && BlockIdentity.minor(rdev)==17,"Linux dev_t extraction");
  long high=((0xabcdeL&~0xfffL)<<32)|((0xabcdeL&0xfffL)<<8)|((0xfedcbL&~0xffL)<<12)|(0xfedcbL&0xffL);
  require(BlockIdentity.major(high)==0xabcdeL && BlockIdentity.minor(high)==0xfedcbL,"extended Linux dev_t extraction");
  reject("/dev/block/sde17","PARTNAME=boot_a","259:17",rdev);
  reject("/dev/block/sde17","PARTNAME=linux","259:17",rdev);
  reject("/dev/block/sde17","PARTNAME=boot_b","259:18",rdev);
  reject("/dev/block/sde17","PARTNAME=boot_b\nPARTNAME=boot_b","259:17",rdev);
  reject("/dev/block/sde17","MAJOR=259","259:17",rdev);
  reject("/dev/block/by-name/boot_b","PARTNAME=boot_b","259:17",rdev);
  reject("/tmp/sde17","PARTNAME=boot_b","259:17",rdev);
  reject("/dev/block/../sde17","PARTNAME=boot_b","259:17",rdev);
  System.out.println("BlockIdentityTest: PASS ("+assertions+" assertions)");
 }
}
