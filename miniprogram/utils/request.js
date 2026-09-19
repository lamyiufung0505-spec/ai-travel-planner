// utils/request.js —— 统一网络请求封装
//
// 两条通道，由 app.js 的 globalData.useContainer 决定走哪条：
//   ① callContainer（推荐）：走微信内网链路调云托管服务
//      —— 免域名、免备案、免 request 白名单，体验版/正式版都能用
//   ② wx.request（备用）：直连公网域名
//      —— 云托管默认域名不允许配进白名单，只能开发者工具/真机调试用
//
// ⚠️ 两条通道单次调用超时都受限（云托管 60s / wx.request 60000ms）。
//    行程生成走「异步提交 + 轮询」，所以本封装默认 8000ms 用于天气/轮询等短请求。

// ---------- 通道①：callContainer（内网链路） ----------
function containerRequest(options, g) {
  return new Promise((resolve, reject) => {
    wx.cloud.callContainer({
      config: { env: g.cloudEnv },
      path: options.url,                 // 形如 /api/weather?dest=...
      method: options.method || 'GET',
      data: options.data || {},
      timeout: options.timeout || 8000,
      header: Object.assign(
        {
          'X-WX-SERVICE': g.cloudService,   // 服务名，不是域名
          'content-type': 'application/json'
        },
        options.header || {}
      ),
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else {
          reject({
            code: res.statusCode,
            message: (res.data && (res.data.detail || res.data.message)) || '请求失败'
          });
        }
      },
      fail: (err) => {
        const msg = (err && err.errMsg) || '未知错误';
        reject({
          code: -1,
          message: 'callContainer 失败：' + msg +
            '\n自查：①小程序后台「基础库最低版本」≥ 2.23.0；' +
            '②cloudEnv/cloudService 是否与云托管控制台一致；' +
            '③服务是否已部署且运行中。'
        });
      }
    });
  });
}

// ---------- 通道②：wx.request（公网域名） ----------
function httpRequest(options, g) {
  const apiBase = g.apiBase || '';
  return new Promise((resolve, reject) => {
    wx.request({
      url: apiBase + options.url,
      method: options.method || 'GET',
      data: options.data || {},
      timeout: options.timeout || 8000,
      header: Object.assign({ 'Content-Type': 'application/json' }, options.header || {}),
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else {
          reject({
            code: res.statusCode,
            message: (res.data && (res.data.detail || res.data.message)) || '请求失败'
          });
        }
      },
      fail: (err) => {
        // err.errMsg 形如 "request:fail timeout" / "request:fail url not in domain list"
        reject({ code: -1, message: (err && err.errMsg) || '网络错误' });
      }
    });
  });
}

// ---------- 统一入口 ----------
function request(options) {
  const app = getApp();
  const g = (app && app.globalData) || {};

  const canUseContainer =
    g.useContainer !== false &&
    typeof wx.cloud === 'object' && wx.cloud !== null &&
    typeof wx.cloud.callContainer === 'function';

  return canUseContainer ? containerRequest(options, g) : httpRequest(options, g);
}

module.exports = { request, containerRequest, httpRequest };
