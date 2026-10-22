export async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
  return data;
}
export const post = (url, body, signal) => api(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body), signal});

export async function writeAndVerify(nfc, session, onStatus, signal) {
  if (!("NDEFReader" in window)) throw new Error("此设备不支持浏览器 NFC，请使用树莓派读写器或外部写卡工具。");
  if (!nfc.public_url_configured) throw new Error("请先为装置配置可跨设备访问的纪念页地址。");
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal?.aborted) throw new Error("操作已取消");
  signal?.addEventListener("abort", cancel, {once: true});
  const timeout = setTimeout(cancel, 40000);
  const reader = new NDEFReader();
  try {
    onStatus("请将一枚空白标签贴近设备，保持不动。");
    return await new Promise((resolve, reject) => {
      let phase = "inspect", expectedUid = "";
      const fail = error => { phase = "done"; reject(error); };
      controller.signal.addEventListener("abort", () => fail(new Error("写入已取消或等待超时，请重试。")), {once: true});
      reader.onreadingerror = () => fail(new Error("无法读取标签，请重新放置。"));
      reader.onreading = async event => {
        try {
          if (phase === "writing" || phase === "done") return;
          const urls = [...event.message.records].filter(r => r.recordType === "url").map(r => new TextDecoder().decode(r.data));
          if (!event.serialNumber) throw new Error("无法取得标签 UID，请改用外部读写器。");
          if (phase === "inspect") {
            expectedUid = event.serialNumber;
            if (event.message.records.some(r => r.recordType !== "empty") && !urls.includes(nfc.url)) throw new Error("标签已有其他内容，请换一枚空白标签。");
            phase = "writing";
            // Reserve UID before writing, to reject a tag claimed by another wish.
            await post("/api/nfc/bind", {blessing_session_id: session.id, souvenir_sku: session.selected_souvenir.sku, nfc_uid: expectedUid}, controller.signal);
            if (urls.includes(nfc.url)) {
              phase = "verify";
            } else {
              onStatus("正在写入；完成后请移开标签，再次贴近以回读。");
              await reader.write({records: nfc.records}, {overwrite: false, signal: controller.signal});
              phase = "verify";
              return;
            }
          }
          if (phase === "verify") {
            if (event.serialNumber !== expectedUid || !urls.includes(nfc.url)) throw new Error("回读标签或链接不一致，请重新写入校验。");
            phase = "done";
            resolve(await post("/api/nfc/bind", {blessing_session_id: session.id, souvenir_sku: session.selected_souvenir.sku, nfc_uid: expectedUid, method: "web-nfc", readback_url: nfc.url}, controller.signal));
          }
        } catch (error) { fail(error); }
      };
      reader.scan({signal: controller.signal}).catch(fail);
    });
  } finally {
    clearTimeout(timeout); signal?.removeEventListener("abort", cancel); controller.abort();
  }
}
