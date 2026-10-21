package cn.armada.dualswitch;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.graphics.Color;
import android.view.View;
import android.widget.*;
import org.json.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private TextView state, device, root, slot, linux, image, reasons;
    private Button check, switchButton;
    private boolean busy, ready;
    private int dp(int n) { return (int)(n*getResources().getDisplayMetrics().density+0.5f); }
    private TextView text(LinearLayout parent, int size, String value) {
        TextView v = new TextView(this); v.setTextSize(size); v.setText(value);
        v.setTextColor(Color.rgb(31,41,55)); v.setPadding(0,dp(8),0,dp(8)); parent.addView(v); return v;
    }
    private static String yn(boolean b, String yes, String no) { return b ? yes : no; }
    private static String slotName(int slot) { return slot==0 ? "a" : slot==1 ? "b" : "未知"; }
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout body = new LinearLayout(this); body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(24),dp(24),dp(24),dp(32)); scroll.addView(body); setContentView(scroll);
        scroll.setOnApplyWindowInsetsListener((v,insets) -> {
            android.graphics.Insets bars=insets.getInsets(android.view.WindowInsets.Type.systemBars());
            body.setPadding(dp(24)+bars.left,dp(24)+bars.top,dp(24)+bars.right,dp(32)+bars.bottom);
            return insets;
        });
        scroll.requestApplyInsets();
        text(body,28,"Armada 双启动");
        text(body,16,"Android a → Armada Linux b");
        state=text(body,20,"准备检查");
        device=text(body,16,"设备：OnePlus Pad Pro · OPD2404");
        root=text(body,16,"root：尚未检查");
        slot=text(body,16,"当前槽：尚未检查\n下次启动槽：尚未检查");
        linux=text(body,16,"Linux 分区：尚未检查");
        image=text(body,16,"Armada 镜像：尚未检查");
        reasons=text(body,15,"点击“检查设备”，并在 KernelSU 中授权。");
        check=new Button(this); check.setText("检查设备"); check.setFilterTouchesWhenObscured(true); body.addView(check);
        switchButton=new Button(this); switchButton.setText("切换到 Armada 并重启");
        switchButton.setEnabled(false); switchButton.setFilterTouchesWhenObscured(true); body.addView(switchButton);
        text(body,14,"切换只更改下次启动槽。请先保存 Android 中的工作。");
        check.setOnClickListener(v -> inspect(false));
        switchButton.setOnClickListener(v -> confirm());
    }
    private void setBusy(boolean value) {
        busy=value; check.setEnabled(!value); switchButton.setEnabled(!value && ready);
    }
    private void confirm() {
        if (busy || !ready) return;
        AlertDialog confirmation=new AlertDialog.Builder(this).setTitle("切换到 Armada？")
            .setMessage("将再次检查设备、linux 分区和 boot_b 镜像，然后把下次启动槽设为 b 并重启。\n\n请先保存 Android 中的工作。")
            .setNegativeButton("取消",null)
            .setPositiveButton("切换并重启",(dialog,which) -> inspect(true)).create();
        confirmation.setOnShowListener(dialog -> confirmation.getButton(AlertDialog.BUTTON_POSITIVE)
            .setFilterTouchesWhenObscured(true));
        confirmation.show();
    }
    private void inspect(boolean switching) {
        if (busy) return;
        ready=false; setBusy(true);
        state.setText(switching ? "正在复查并切换…" : "正在检查…");
        reasons.setText(switching ? "正在核对镜像与启动设置。" : "如 KernelSU 弹出请求，请授予 root 权限。");
        String apk = getApplicationInfo().sourceDir;
        worker.execute(() -> {
            ProcessSession.Result result=null; Exception failure=null;
            try { result=RootShell.run(apk,switching); } catch (Exception e) { failure=e; }
            final ProcessSession.Result r=result; final Exception f=failure;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                try {
                    if (f!=null) throw f;
                    JSONObject j=new JSONObject(r.out);
                    if (j.optInt("protocol",-1)!=1) throw new Exception("启动检查返回格式不匹配");
                    if (switching) {
                        ready=false;
                        if (r.exit==0 && j.optBoolean("switchVerified")) {
                            state.setText("已设为 Armada 槽 b");
                            reasons.setText("正在重启。若设备未重启，请重新检查下次启动槽。");
                            slot.setText("当前槽：a\n下次启动槽：b");
                        } else {
                            state.setText("切换已停止");
                            reasons.setText(j.optString("message","已停止切换")+"\n"+j.optString("error","重启命令未完成"));
                        }
                    } else if (j.has("root")) {
                        render(j,r.exit);
                    } else {
                        throw new Exception(j.optString("error","root 检查失败"));
                    }
                } catch (Exception e) {
                    ready=false; state.setText(switching ? "切换未完成" : "检查未完成");
                    String detail=e.getMessage()==null ? e.getClass().getSimpleName() : e.getMessage();
                    if (r!=null && r.out.isEmpty()) {
                        detail="无法运行 root helper。请检查 KernelSU 授权。";
                        if (!r.err.isEmpty()) detail+="\n"+r.err;
                    }
                    reasons.setText(detail+(switching ? "\n请重新检查下次启动槽。" : ""));
                } finally { setBusy(false); }
            });
        });
    }
    private void render(JSONObject j, int exit) throws Exception {
        device.setText("设备："+j.getString("model")+" · "+j.getString("device"));
        root.setText("root："+yn(j.getBoolean("root"),"已授权","未授权"));
        slot.setText("当前槽："+slotName(j.getInt("current"))+"\n下次启动槽："+slotName(j.getInt("active"))
            +"\n启动 HAL："+yn(j.getBoolean("halVerified"),"AIDL 已校验","检查失败"));
        boolean linuxOk=j.getBoolean("linuxBlock") && j.getLong("linuxBytes")==TargetConfig.LINUX_BYTES
            && TargetConfig.LINUX_PARTLABEL.equals(j.getString("partlabel"));
        linux.setText("Linux 分区："+yn(linuxOk,"linux · 64 GiB","未匹配"));
        image.setText("Armada 镜像："+yn(j.getBoolean("hashMatches"),"boot_b 校验通过",
            j.getBoolean("deploymentReady") ? "boot_b 校验未通过" : "等待部署配置"));
        JSONArray blocks=j.getJSONArray("blockers");
        ready=exit==0 && j.getBoolean("ready") && blocks.length()==0;
        state.setText(ready ? "可以切换" : "尚未就绪");
        StringBuilder lines=new StringBuilder();
        for (int i=0;i<blocks.length();i++) { if(i>0)lines.append('\n'); lines.append("• ").append(blocks.getString(i)); }
        reasons.setText(ready ? "设备、分区、镜像与启动设置已通过检查。" : lines.toString());
    }
    @Override protected void onDestroy() { worker.shutdown(); super.onDestroy(); }
}
