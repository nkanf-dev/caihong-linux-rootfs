package cn.armada.dualswitch;
import java.io.*;
import java.nio.file.Files;
public final class ImageDigestTest {
    static int assertions;
    static void require(boolean p,String message){assertions++;if(!p)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception{
        File image=Files.createTempFile("armada-digest-test-",".img").toFile();
        try{
            Files.write(image.toPath(),new byte[]{97,98,99,0,0,0,0});
            require(ImageDigest.prefix(image,3).equals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),"known SHA256 of abc prefix");
            require(!ImageDigest.prefix(image,7).equals(ImageDigest.prefix(image,3)),"partition padding excluded");
            boolean shortRead=false;try{ImageDigest.prefix(image,8);}catch(EOFException e){shortRead=true;}
            require(shortRead,"short boot block fails");
            boolean zero=false;try{ImageDigest.prefix(image,0);}catch(Exception e){zero=true;}
            require(zero,"zero image length rejected");
        }finally{Files.delete(image.toPath());}
        System.out.println("ImageDigestTest: PASS ("+assertions+" assertions)");
    }
}
