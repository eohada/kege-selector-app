(() => {
  const frame = document.querySelector('[data-classroom-frame]');
  const poster = document.querySelector('[data-poster]');
  const status = document.querySelector('[data-live-status]');
  const loadButton = document.querySelector('[data-load-class]');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const storySteps = [...document.querySelectorAll('[data-step]')];
  const railFill = document.querySelector('[data-rail-fill]');

  const scrollToClass = () => {
    document.querySelector('#classroom')?.scrollIntoView({
      behavior: reducedMotion.matches ? 'auto' : 'smooth',
      block: 'start'
    });
  };

  document.querySelectorAll('[data-enter-class]').forEach((control) => {
    control.addEventListener('click', (event) => {
      event.preventDefault();
      scrollToClass();
      window.setTimeout(() => loadButton?.focus({ preventScroll: true }), reducedMotion.matches ? 0 : 450);
    });
  });

  const loadClass = () => {
    if (!frame || frame.src) return;
    if (poster) poster.hidden = true;
    frame.hidden = false;
    status.textContent = 'Загружается локальный демо-урок в режиме ученика…';
    frame.src = '/lesson/2174/room';
    frame.addEventListener('load', () => {
      status.textContent = 'Реальная комната открыта в режиме ученика. Действия внутри доступны по возможностям этой роли.';
    }, { once: true });
    frame.addEventListener('error', () => {
      status.textContent = 'Не удалось загрузить урок. Откройте его в отдельном окне.';
      if (poster) poster.hidden = false;
      frame.hidden = true;
    }, { once: true });
  };

  loadButton?.addEventListener('click', loadClass);

  const setActiveStep = (step) => {
    storySteps.forEach((item, index) => item.classList.toggle('is-active', index === step));
    if (railFill && storySteps.length > 1) {
      railFill.style.height = `${(step / (storySteps.length - 1)) * 100}%`;
    }
  };

  if ('IntersectionObserver' in window && storySteps.length) {
    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) setActiveStep(Number(visible.target.dataset.step));
    }, { rootMargin: '-35% 0px -38% 0px', threshold: [0.1, 0.25, 0.5, 0.75] });
    storySteps.forEach((step) => observer.observe(step));
  }

  if (new URLSearchParams(window.location.search).has('capture')) {
    const captureBar = document.createElement('div');
    captureBar.className = 'capture-bar';
    captureBar.setAttribute('aria-label', 'Запись этой вкладки');
    captureBar.innerHTML = '<span class="capture-status" aria-live="polite">Запись только этой вкладки</span><button type="button" data-record-start>Начать запись</button><button type="button" data-record-stop hidden>Остановить и сохранить</button>';
    document.body.append(captureBar);

    const captureStatus = captureBar.querySelector('.capture-status');
    const recordStart = captureBar.querySelector('[data-record-start]');
    const recordStop = captureBar.querySelector('[data-record-stop]');
    let mediaRecorder;
    let captureStream;
    let chunks = [];

    recordStart.addEventListener('click', async () => {
      if (!navigator.mediaDevices?.getDisplayMedia || !window.MediaRecorder) {
        captureStatus.textContent = 'Запись экрана недоступна в этом браузере.';
        return;
      }
      try {
        captureStream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 30 }, audio: false });
        const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
          ? 'video/webm;codecs=vp9'
          : 'video/webm';
        mediaRecorder = new MediaRecorder(captureStream, { mimeType });
        chunks = [];
        mediaRecorder.addEventListener('dataavailable', (event) => {
          if (event.data?.size) chunks.push(event.data);
        });
        mediaRecorder.addEventListener('stop', () => {
          const recording = new Blob(chunks, { type: mimeType });
          const downloadUrl = URL.createObjectURL(recording);
          const download = document.createElement('a');
          download.href = downloadUrl;
          download.download = 'boostudy-sprint-2.4-living-classroom.webm';
          download.click();
          window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 60_000);
          captureStream?.getTracks().forEach((track) => track.stop());
          captureStatus.textContent = `Видео сохранено · ${(recording.size / 1_000_000).toFixed(1)} МБ`;
          recordStart.hidden = false;
          recordStop.hidden = true;
          captureBar.classList.remove('is-recording');
        }, { once: true });
        mediaRecorder.start(1000);
        captureStatus.textContent = 'REC · записывается выбранная вкладка';
        recordStart.hidden = true;
        recordStop.hidden = false;
        captureBar.classList.add('is-recording');
        captureStream.getVideoTracks()[0]?.addEventListener('ended', () => {
          if (mediaRecorder?.state === 'recording') mediaRecorder.stop();
        }, { once: true });
      } catch (error) {
        captureStatus.textContent = error.name === 'NotAllowedError'
          ? 'Запись отменена. Можно выбрать вкладку и повторить.'
          : 'Не удалось начать запись в этом браузере.';
      }
    });

    recordStop.addEventListener('click', () => {
      if (mediaRecorder?.state === 'recording') mediaRecorder.stop();
    });
  }
})();
