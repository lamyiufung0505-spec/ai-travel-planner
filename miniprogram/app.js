// app.js —— 小程序入口
App({
  globalData: {
    // ============================================================
    //  后端调用方式：改 useContainer 一个开关即可切换
    // ============================================================
    //  ① useContainer: true  ← 推荐，走微信内网链路调云托管服务
    //     用 wx.cloud.callContainer，不经过公网域名：
    //       · 免域名、免备案
    //       · 免 request 合法域名白名单
    //       · 体验版 / 正式版 / 朋友扫码 都能用
    //     前提：
    //       a) 小程序后台「设置 → 功能设置 → 基础库最低版本」≥ 2.23.0
    //       b) 下面 cloudEnv / cloudService 与控制台里的一致
    //       c) 服务已部署成功（状态是运行中）
    //  ② useContainer: false ← 备用，直连公网域名（wx.request）
    //     注意：云托管默认域名 *.run.tcloudbase.com 微信不允许配进 request 白名单，
    //     所以这条只能用于「开发者工具（勾选不校验合法域名）」或「真机调试」，
    //     体验版 / 正式版会直接 request:fail。
    // ============================================================
    useContainer: true,

    // 云托管环境 ID / 服务名（在云托管控制台 → 服务列表里核对）
    cloudEnv: "cloud1-d7gen8bfi94ca34eb",
    cloudService: "travel-plan",

    // 方式② 用的公网域名（本地调试时也可改成本机地址）：
    //   本机模拟器： "http://127.0.0.1:8000"
    //   同 WiFi 真机： "http://192.168.3.143:8000"
    apiBase: "https://travel-plan-296003-11-1467317729.sh.run.tcloudbase.com"
  },

  onLaunch() {
    // callContainer 依赖 wx.cloud，先初始化云开发环境
    if (!wx.cloud) {
      console.warn('[app] 当前基础库不支持 wx.cloud，请把基础库调到 2.2.3 以上（建议 ≥ 2.23.0）');
      return;
    }
    const env = this.globalData.cloudEnv;
    try {
      wx.cloud.init({ env, traceUser: true });
      console.log('[app] wx.cloud.init OK, env =', env);
    } catch (e) {
      // 某些情况下指定 env 会失败（例如该 ID 不是云开发环境），退化为不指定 env。
      // callContainer 每次调用时还会用 config.env 再指定一次，所以不影响使用。
      console.warn('[app] wx.cloud.init(env) 失败，退化为不指定 env：', e);
      try {
        wx.cloud.init({ traceUser: true });
        console.log('[app] wx.cloud.init OK (未指定 env)');
      } catch (e2) {
        console.error('[app] wx.cloud.init 彻底失败：', e2);
      }
    }
  }
});
