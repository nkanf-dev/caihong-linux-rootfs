package android.os;
import java.util.*;
public final class Parcel {
 final List<Object> data=new ArrayList<>(); int cursor;
 public static int obtained,recycled;
 public static Parcel obtain(){obtained++;return new Parcel();}
 public void recycle(){recycled++;}
 public void writeInterfaceToken(String s){data.add(s);}
 public void writeInt(int i){data.add(i);}
 public void writeString(String s){data.add(s);}
 public int readInt(){return (Integer)data.get(cursor++);}
 public String readString(){return (String)data.get(cursor++);}
 public void readException(){if(readInt()!=0)throw new SecurityException("HAL denied");}
 public int dataAvail(){return 4*(data.size()-cursor);}
 public void enforceToken(String s){if(!s.equals(readString()))throw new AssertionError("descriptor token");}
}
