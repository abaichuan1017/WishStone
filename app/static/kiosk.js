let mediaRecorder = null;
let chunks = [];
let audioBlob = null;
let isRecording = false;

const recordBtn = document.getElementById("recordBtn");
const submitBtn = document.getElementById("submitBtn");
const wishInput = document.getElementById("wishInput");
const previewAudio = document.getElementById("previewAudio");
const result = document.getElementById("result");
const replyText = document.getElementById("replyText");
const blessingLink = document.getElementById("blessingLink");
const meta = document.getElementById("meta");

recordBtn.addEventListener("click", async () => {
  if (!isRecording) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      chunks = [];
      mediaRecorder.ondataavailable = (e) => chunks.push(e.data);
      mediaRecorder.onstop = () => {
        audioBlob = new Blob(chunks, { type: "audio/webm" });
        previewAudio.src = URL.createObjectURL(audioBlob);
        previewAudio.hidden = false;
      };
      mediaRecorder.start();
      isRecording = true;
      recordBtn.textContent = "停止录音";
    } catch (error) {
      alert("无法访问麦克风，请确认浏览器权限。");
    }
  } else {
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach((track) => track.stop());
    isRecording = false;
    recordBtn.textContent = "开始录音";
  }
});

submitBtn.addEventListener("click", async () => {
  submitBtn.disabled = true;
  submitBtn.textContent = "生成中...";

  try {
    const form = new FormData();
    form.append("venue_id", "venue-liangzhu");
    form.append("device_id", "device-demo-001");
    form.append("user_text", wishInput.value || "");
    if (audioBlob) {
      form.append("audio", audioBlob, "wishstone.webm");
    }

    const res = await fetch("/api/sessions", {
      method: "POST",
      body: form,
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "生成失败");
    }

    const session = data.session;
    result.hidden = false;
    replyText.textContent = session.ai_reply_text;
    blessingLink.href = session.blessing_page_url;
    meta.textContent = `识别: ${session.asr.text} | 意图: ${session.intent.intent}/${session.intent.sub_intent} | 情绪: ${session.intent.emotion}`;
  } catch (error) {
    alert(error.message || "请求失败");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "生成祈福回应";
  }
});
