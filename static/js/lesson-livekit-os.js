/**
 * BooStudy OS — Native LiveKit Video Conference Controller
 * Self-hosted WebRTC 1-on-1 video integration for lessons.
 */
(() => {
  'use strict';

  class LessonLiveKitController {
    constructor() {
      this.lessonId = null;
      this.isTeacher = false;
      this.room = null;
      this.token = null;
      this.serverUrl = null;
      this.roomName = null;
      this.backupUrl = '';

      // Media tracks
      this.previewStream = null;
      this.localAudioTrack = null;
      this.localVideoTrack = null;
      this.screenTrack = null;
      this.selectedAudioId = '';
      this.selectedVideoId = '';
      this.selectedAudioOutputId = '';

      // Audio analysis for meter
      this.audioContext = null;
      this.analyser = null;
      this.meterAnimId = null;

      // State flags
      this.isConnected = false;
      this.isConnecting = false;
      this.isAudioMuted = false;
      this.isVideoMuted = false;
      this.isScreenSharing = false;
      this.isPipActive = false;

      // Remote participants
      this.remoteParticipants = new Map();
      this.primaryRemoteIdentity = null;
      this.activeScreenshareIdentity = null;

      this.init();
    }

    init() {
      this.resolveLessonContext();

      const onReady = () => {
        this.resolveLessonContext();
        this.bindUI();
        this.populateDeviceSelectors();
      };

      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', onReady);
      } else {
        onReady();
      }

      if (navigator.mediaDevices?.addEventListener) {
        navigator.mediaDevices.addEventListener('devicechange', () => {
          this.populateDeviceSelectors();
        });
      }
    }

    resolveLessonContext() {
      // 1. Try #trainer-os-config script tag
      try {
        const cfgEl = document.getElementById('trainer-os-config');
        if (cfgEl && cfgEl.textContent) {
          const cfg = JSON.parse(cfgEl.textContent);
          if (cfg.lesson_id) this.lessonId = Number(cfg.lesson_id);
          if (typeof cfg.is_studio_teacher !== 'undefined') {
            this.isTeacher = Boolean(cfg.is_studio_teacher);
          }
        }
      } catch (_) {}

      // 2. Try window.trainerOsConfig
      if (!this.lessonId && window.trainerOsConfig) {
        if (window.trainerOsConfig.lesson_id) this.lessonId = Number(window.trainerOsConfig.lesson_id);
        if (typeof window.trainerOsConfig.is_studio_teacher !== 'undefined') {
          this.isTeacher = Boolean(window.trainerOsConfig.is_studio_teacher);
        }
      }

      // 3. Try #video-window dataset
      const win = document.getElementById('video-window');
      if (win) {
        if (!this.lessonId && win.dataset.lessonId) {
          this.lessonId = Number(win.dataset.lessonId);
        }
        if (typeof win.dataset.teacher !== 'undefined') {
          this.isTeacher = win.dataset.teacher === 'true';
        }
      }

      // 4. Fallback: extract lesson ID from current URL
      if (!this.lessonId) {
        const m = window.location.pathname.match(/\/lesson\/(?:trainer\/)?(\d+)/);
        if (m) this.lessonId = Number(m[1]);
      }
    }

    bindUI() {
      // 1. Lobby Join Button
      const joinBtn = document.getElementById('livekit-btn-join');
      if (joinBtn) {
        joinBtn.onclick = (e) => {
          e.preventDefault();
          this.joinRoom();
        };
      }

      // 2. Custom Device Select Triggers
      this.setupCustomSelectTrigger('mic');
      this.setupCustomSelectTrigger('cam');
      this.setupCustomSelectTrigger('speaker');

      // Close custom select menus on click outside
      document.addEventListener('click', (e) => {
        if (!e.target.closest('.lesson-video-custom-select')) {
          this.closeAllSelectMenus();
        }
      });

      // 3. Active Call Toolbar Controls
      document.getElementById('livekit-btn-mic')?.addEventListener('click', () => this.toggleMicrophone());
      document.getElementById('livekit-btn-cam')?.addEventListener('click', () => this.toggleCamera());
      document.getElementById('livekit-btn-screen')?.addEventListener('click', () => this.toggleScreenShare());
      document.getElementById('livekit-btn-pip')?.addEventListener('click', () => this.togglePipMode());
      document.getElementById('livekit-btn-hangup')?.addEventListener('click', () => this.leaveRoom());

      // 4. Teacher Admin Mute Student
      document.getElementById('livekit-btn-admin-mute')?.addEventListener('click', () => this.teacherMuteStudent());

      // 5. More Menu
      const moreBtn = document.getElementById('livekit-btn-more');
      const moreMenu = document.getElementById('livekit-more-menu');
      if (moreBtn && moreMenu) {
        moreBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          moreMenu.hidden = !moreMenu.hidden;
        });
        document.addEventListener('click', () => { moreMenu.hidden = true; });
      }

      // 6. Backup call redirect
      document.getElementById('livekit-btn-backup-call')?.addEventListener('click', () => {
        if (this.backupUrl) {
          window.open(this.backupUrl, '_blank', 'noopener,noreferrer');
        } else {
          window.alert('Преподаватель пока не настроил резервную ссылку.');
        }
      });

      // 7. Floating PiP controls
      document.getElementById('video-pip-restore')?.addEventListener('click', () => this.restoreFromPip());
      document.getElementById('video-pip-mic')?.addEventListener('click', () => this.toggleMicrophone());
      document.getElementById('video-pip-cam')?.addEventListener('click', () => this.toggleCamera());
      document.getElementById('video-pip-close')?.addEventListener('click', () => this.closePipToBackground());

      // 8. Window controls (Titlebar buttons)
      document.getElementById('video-dot-close')?.addEventListener('click', () => this.hideWindow());
      document.getElementById('video-dot-minimize')?.addEventListener('click', () => this.togglePipMode());
      document.getElementById('video-dot-maximize')?.addEventListener('click', () => this.toggleMaximize());

      // 9. Setup Draggable PiP
      this.setupDraggablePip();
    }

    setupCustomSelectTrigger(type) {
      const trigger = document.getElementById(`custom-select-${type}-trigger`);
      const menu = document.getElementById(`custom-select-${type}-menu`);
      const wrap = document.getElementById(`custom-select-${type}-wrap`);
      if (!trigger || !menu) return;

      trigger.onclick = (e) => {
        e.stopPropagation();
        e.preventDefault();
        const isOpen = !menu.hidden;
        this.closeAllSelectMenus();
        if (!isOpen) {
          menu.hidden = false;
          trigger.classList.add('is-open');
          trigger.setAttribute('aria-expanded', 'true');
          if (wrap) wrap.classList.add('is-active');

          // Check if space below is too small, open upward if needed
          const rect = trigger.getBoundingClientRect();
          const lobbyEl = document.getElementById('livekit-view-lobby');
          const lobbyBottom = lobbyEl ? lobbyEl.getBoundingClientRect().bottom : window.innerHeight;
          const spaceBelow = lobbyBottom - rect.bottom;
          if (wrap) {
            wrap.classList.toggle('open-upward', spaceBelow < 150);
          }
        }
      };
    }

    closeAllSelectMenus() {
      ['mic', 'cam', 'speaker'].forEach(type => {
        const trigger = document.getElementById(`custom-select-${type}-trigger`);
        const menu = document.getElementById(`custom-select-${type}-menu`);
        const wrap = document.getElementById(`custom-select-${type}-wrap`);
        if (menu) menu.hidden = true;
        if (trigger) {
          trigger.classList.remove('is-open');
          trigger.setAttribute('aria-expanded', 'false');
        }
        if (wrap) {
          wrap.classList.remove('is-active', 'open-upward');
        }
      });
    }

    /* =====================================================================
       1. WINDOW & OS INTEGRATION
       ===================================================================== */

    openWindow() {
      const win = document.getElementById('video-window');
      if (!win) return;

      if (this.isPipActive) {
        this.restoreFromPip();
      }

      win.style.display = 'flex';
      win.classList.remove('hidden', 'window-minimized');
      win.style.opacity = '1';

      if (window.windowManager) {
        window.windowManager.bringToFront(win);
        window.windowManager.saveWindowVisibility(win, true);
      }

      if (!this.isConnected && !this.previewStream) {
        this.startLobbyPreview();
      }
    }

    hideWindow() {
      const win = document.getElementById('video-window');
      if (!win) return;
      win.classList.add('hidden');
      win.style.display = 'none';

      if (window.windowManager) {
        window.windowManager.saveWindowVisibility(win, false);
      }
      // Audio call continues in background!
    }

    toggleWindow() {
      const win = document.getElementById('video-window');
      if (!win) return;
      if (win.classList.contains('hidden') || win.style.display === 'none') {
        this.openWindow();
      } else {
        this.hideWindow();
      }
    }

    toggleMaximize() {
      const win = document.getElementById('video-window');
      if (!win) return;
      win.classList.toggle('window-maximized');
    }

    /* =====================================================================
       2. PRE-JOIN LOBBY & CUSTOM DEVICE SELECTORS
       ===================================================================== */

    async startLobbyPreview() {
      try {
        await this.populateDeviceSelectors();

        const videoConstraint = (this.selectedVideoId && this.selectedVideoId !== 'default')
          ? { deviceId: { exact: this.selectedVideoId } }
          : true;
        const audioConstraint = (this.selectedAudioId && this.selectedAudioId !== 'default')
          ? { deviceId: { exact: this.selectedAudioId } }
          : true;

        let stream = null;
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            video: videoConstraint,
            audio: audioConstraint
          });
        } catch (e1) {
          console.warn('[LiveKit] Full A/V preview unavailable, trying audio-only:', e1);
          try {
            stream = await navigator.mediaDevices.getUserMedia({
              video: false,
              audio: audioConstraint
            });
          } catch (e2) {
            console.warn('[LiveKit] Audio-only preview also unavailable:', e2);
          }
        }

        if (stream) {
          this.previewStream = stream;
          const previewEl = document.getElementById('livekit-preview-video');
          const avatarPlaceholder = document.getElementById('livekit-preview-avatar');

          if (stream.getVideoTracks().length > 0 && previewEl) {
            previewEl.srcObject = stream;
            previewEl.style.display = 'block';
            previewEl.play().catch(() => {});
            if (avatarPlaceholder) avatarPlaceholder.style.display = 'none';
          } else {
            if (previewEl) previewEl.style.display = 'none';
            if (avatarPlaceholder) avatarPlaceholder.style.display = 'flex';
          }

          if (stream.getAudioTracks().length > 0) {
            this.startAudioMeter(stream);
          }

          // Permissions unlocked real device names, update dropdown labels!
          await this.populateDeviceSelectors();
        } else {
          const avatarPlaceholder = document.getElementById('livekit-preview-avatar');
          if (avatarPlaceholder) avatarPlaceholder.style.display = 'flex';
        }
      } catch (err) {
        console.warn('[LiveKit] Lobby preview camera/mic access denied or unavailable:', err);
        const avatarPlaceholder = document.getElementById('livekit-preview-avatar');
        if (avatarPlaceholder) avatarPlaceholder.style.display = 'flex';
      }
    }

    stopLobbyPreview() {
      if (this.previewStream) {
        try {
          this.previewStream.getTracks().forEach(t => t.stop());
        } catch (_) {}
        this.previewStream = null;
      }
      const previewEl = document.getElementById('livekit-preview-video');
      if (previewEl) {
        previewEl.srcObject = null;
      }
      this.stopAudioMeter();
    }

    startAudioMeter(stream) {
      this.stopAudioMeter();
      try {
        const audioTracks = stream.getAudioTracks();
        if (!audioTracks.length) return;

        const AudioContext = window.AudioContext || window.webkitAudioContext;
        this.audioContext = new AudioContext();
        const source = this.audioContext.createMediaStreamSource(stream);
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 64;
        source.connect(this.analyser);

        const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
        const meterFill = document.getElementById('livekit-mic-meter-fill');

        const updateMeter = () => {
          if (!this.analyser) return;
          this.analyser.getByteFrequencyData(dataArray);
          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
          const avg = sum / dataArray.length;
          const pct = Math.min(100, Math.round((avg / 128) * 100));
          if (meterFill) meterFill.style.width = `${pct}%`;
          this.meterAnimId = requestAnimationFrame(updateMeter);
        };
        updateMeter();
      } catch (_) {}
    }

    stopAudioMeter() {
      if (this.meterAnimId) {
        cancelAnimationFrame(this.meterAnimId);
        this.meterAnimId = null;
      }
      if (this.audioContext && this.audioContext.state !== 'closed') {
        this.audioContext.close().catch(() => {});
        this.audioContext = null;
      }
    }

    async populateDeviceSelectors() {
      if (!navigator.mediaDevices?.enumerateDevices) return;
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();

        const mics = devices.filter(d => d.kind === 'audioinput');
        const cams = devices.filter(d => d.kind === 'videoinput');
        const spks = devices.filter(d => d.kind === 'audiooutput');

        this.renderCustomDeviceMenu('mic', mics, 'Микрофон');
        this.renderCustomDeviceMenu('cam', cams, 'Камера');
        this.renderCustomDeviceMenu('speaker', spks, 'Динамики');

      } catch (e) {
        console.warn('[LiveKit] Device enumeration error:', e);
      }
    }

    renderCustomDeviceMenu(type, deviceList, fallbackLabel) {
      const menu = document.getElementById(`custom-select-${type}-menu`);
      const labelEl = document.getElementById(`custom-select-${type}-label`);
      const hiddenSelect = document.getElementById(`livekit-select-${type}`);

      if (!menu || !labelEl) return;
      menu.innerHTML = '';
      if (hiddenSelect) hiddenSelect.innerHTML = '';

      // Ensure we always have selectable items
      const items = (deviceList && deviceList.length > 0) ? [...deviceList] : [
        { deviceId: 'default', label: `${fallbackLabel} по умолчанию` }
      ];

      let activeId = '';
      if (type === 'mic') activeId = this.selectedAudioId;
      if (type === 'cam') activeId = this.selectedVideoId;
      if (type === 'speaker') activeId = this.selectedAudioOutputId;

      if (!activeId || !items.some(d => d.deviceId === activeId)) {
        activeId = items[0].deviceId;
      }

      items.forEach((d, idx) => {
        const rawLabel = (d.label || '').trim();
        const deviceName = rawLabel || `${fallbackLabel} ${idx + 1}`;
        const isSelected = d.deviceId === activeId;

        if (isSelected) {
          labelEl.textContent = deviceName;
        }

        // 1. Custom menu button
        const itemBtn = document.createElement('button');
        itemBtn.type = 'button';
        itemBtn.className = `lesson-video-select-item${isSelected ? ' is-selected' : ''}`;
        itemBtn.textContent = deviceName;
        itemBtn.title = deviceName;
        itemBtn.dataset.deviceId = d.deviceId;

        itemBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          e.preventDefault();
          menu.querySelectorAll('.lesson-video-select-item').forEach(b => b.classList.remove('is-selected'));
          itemBtn.classList.add('is-selected');
          labelEl.textContent = deviceName;
          this.closeAllSelectMenus();
          this.onDeviceChange(type, d.deviceId);
        });

        menu.appendChild(itemBtn);

        // 2. Hidden standard select for sync
        if (hiddenSelect) {
          const opt = document.createElement('option');
          opt.value = d.deviceId;
          opt.textContent = deviceName;
          opt.selected = isSelected;
          hiddenSelect.appendChild(opt);
        }
      });

      if (type === 'mic') this.selectedAudioId = activeId;
      if (type === 'cam') this.selectedVideoId = activeId;
      if (type === 'speaker') this.selectedAudioOutputId = activeId;
    }

    async onDeviceChange(type, deviceId) {
      if (type === 'mic') this.selectedAudioId = deviceId;
      if (type === 'cam') this.selectedVideoId = deviceId;
      if (type === 'speaker') this.selectedAudioOutputId = deviceId;

      if (this.isConnected && this.room) {
        try {
          if (type === 'mic' && this.room.switchActiveDevice) {
            await this.room.switchActiveDevice('audioinput', deviceId);
          } else if (type === 'cam' && this.room.switchActiveDevice) {
            await this.room.switchActiveDevice('videoinput', deviceId);
          } else if (type === 'speaker' && this.room.switchActiveDevice) {
            await this.room.switchActiveDevice('audiooutput', deviceId);
          }
        } catch (err) {
          console.error('[LiveKit] Failed to switch active device during call:', err);
        }
      } else {
        // In lobby preview, restart preview with new device
        this.stopLobbyPreview();
        this.startLobbyPreview();
      }
    }

    /* =====================================================================
       3. ROOM CONNECTION & TOKEN
       ===================================================================== */

    async joinRoom() {
      if (this.isConnected || this.isConnecting) return;
      this.isConnecting = true;
      this.updateStatusBadge('connecting', 'Подключение...');

      const joinBtn = document.getElementById('livekit-btn-join');
      if (joinBtn) {
        joinBtn.disabled = true;
        joinBtn.innerHTML = '<i class="ph-bold ph-spinner animate-spin"></i> Соединение...';
      }

      const LivekitClient = window.LivekitClient;
      if (!LivekitClient) {
        console.error('[LiveKit] LivekitClient SDK not loaded.');
        this.updateStatusBadge('error', 'Ошибка SDK');
        if (joinBtn) {
          joinBtn.disabled = false;
          joinBtn.textContent = 'Ошибка загрузки SDK. Повторить';
        }
        this.isConnecting = false;
        return;
      }

      try {
        if (!this.lessonId) {
          this.resolveLessonContext();
        }
        if (!this.lessonId) {
          throw new Error('ID урока не определен');
        }

        // 1. Fetch token from BooStudy backend
        const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const resp = await fetch(`/lesson/${this.lessonId}/livekit/token`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrf
          }
        });
        const data = await resp.json();

        if (!data.success || !data.token) {
          throw new Error(data.error || 'Не удалось получить токен видеосвязи');
        }

        this.token = data.token;
        this.roomName = data.room_name;
        this.backupUrl = data.backup_call_url || '';

        // Dynamically resolve serverUrl: match browser host if local
        let serverUrl = data.url;
        try {
          const u = new URL(serverUrl);
          if ((u.hostname === 'localhost' || u.hostname === '127.0.0.1') && window.location.hostname) {
            u.hostname = window.location.hostname;
            serverUrl = u.toString();
          }
        } catch (_) {}
        if (window.location.protocol === 'https:' && serverUrl.startsWith('ws://')) {
          serverUrl = 'wss://' + serverUrl.slice(5);
        }
        this.serverUrl = serverUrl;

        // 2. Stop lobby preview & wait for OS camera driver release
        this.stopLobbyPreview();
        await new Promise(r => setTimeout(r, 150));

        // 3. Initialize LiveKit Room instance
        this.room = new LivekitClient.Room({
          adaptiveStream: false,
          dynacast: false,
          videoCaptureDefaults: {
            resolution: LivekitClient.VideoPresets.h720,
            deviceId: (this.selectedVideoId && this.selectedVideoId !== 'default') ? this.selectedVideoId : undefined
          },
          audioCaptureDefaults: {
            deviceId: (this.selectedAudioId && this.selectedAudioId !== 'default') ? this.selectedAudioId : undefined
          }
        });

        this.setupRoomEvents();

        // 4. Connect to Room
        await this.room.connect(this.serverUrl, this.token);

        this.isConnected = true;
        this.isConnecting = false;
        this.updateStatusBadge('connected', 'В сети');
        this.setDockStatusActive(true);

        // Switch UI to active call view immediately upon connect
        this.showActiveCallView();

        // 5. Publish Local Tracks (HQ, no simulcast)
        await this.publishLocalTracks();

        // 6. Initial sync with any already-connected participants
        this.syncRemoteParticipantUI();

      } catch (err) {
        console.error('[LiveKit] Join failed:', err);
        this.isConnecting = false;
        this.updateStatusBadge('error', 'Ошибка сети');
        if (joinBtn) {
          joinBtn.disabled = false;
          joinBtn.innerHTML = '<i class="ph-bold ph-video-camera"></i> Присоединиться к видеоуроку';
        }
        this.toast(`Не удалось подключиться к серверу LiveKit (${err.message || 'сеть недоступна'})`);

        if (this.backupUrl && window.confirm('Не удалось связаться с сервером видеосвязи. Открыть резервную ссылку на звонок?')) {
          window.open(this.backupUrl, '_blank', 'noopener,noreferrer');
        }
      }
    }

    async publishLocalTracks() {
      const LivekitClient = window.LivekitClient;
      if (!this.room || !LivekitClient) return;

      // 1. Publish Audio
      try {
        const audioTrack = await LivekitClient.createLocalAudioTrack({
          deviceId: (this.selectedAudioId && this.selectedAudioId !== 'default') ? this.selectedAudioId : undefined
        });
        this.localAudioTrack = audioTrack;
        await this.room.localParticipant.publishTrack(audioTrack);
      } catch (err) {
        console.warn('[LiveKit] Could not publish local audio track:', err);
      }

      // 2. Publish Video (Full HD 720/1080 with simulcast: false for crystal clarity)
      try {
        const videoTrack = await LivekitClient.createLocalVideoTrack({
          resolution: LivekitClient.VideoPresets.h720,
          deviceId: (this.selectedVideoId && this.selectedVideoId !== 'default') ? this.selectedVideoId : undefined
        });
        this.localVideoTrack = videoTrack;
        await this.room.localParticipant.publishTrack(videoTrack, {
          simulcast: false,
          videoCodec: 'vp8'
        });
        const localVideoEl = document.getElementById('livekit-local-video');
        if (localVideoEl) videoTrack.attach(localVideoEl);
      } catch (err) {
        console.warn('[LiveKit] Could not publish local video track (audio-only):', err);
        this.toast('Камера недоступна, звонок запущен со звуком');
      }
    }

    setupRoomEvents() {
      const LivekitClient = window.LivekitClient;
      const { RoomEvent } = LivekitClient;

      this.room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
        if (publication?.setVideoQuality && LivekitClient?.VideoQuality) {
          publication.setVideoQuality(LivekitClient.VideoQuality.HIGH);
        }
        this.syncRemoteParticipantUI();
      });

      this.room.on(RoomEvent.TrackPublished, (publication, participant) => {
        this.syncRemoteParticipantUI();
      });

      this.room.on(RoomEvent.TrackUnsubscribed, (track, publication, participant) => {
        track.detach();
        if (track.source === LivekitClient.Track.Source.ScreenShare) {
          this.handleScreenShareEnded(participant);
        } else {
          this.syncRemoteParticipantUI();
        }
      });

      this.room.on(RoomEvent.TrackUnpublished, (publication, participant) => {
        if (publication.source === LivekitClient.Track.Source.ScreenShare) {
          this.handleScreenShareEnded(participant);
        } else {
          this.syncRemoteParticipantUI();
        }
      });

      this.room.on(RoomEvent.ParticipantConnected, (participant) => {
        this.remoteParticipants.set(participant.identity, participant);
        this.syncRemoteParticipantUI();
        this.toast(`${participant.name || 'Собеседник'} подключился к уроку`);
      });

      this.room.on(RoomEvent.ParticipantDisconnected, (participant) => {
        this.remoteParticipants.delete(participant.identity);
        this.syncRemoteParticipantUI();
        this.toast(`${participant.name || 'Собеседник'} покинул звонок`);
      });

      this.room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        const remoteBadge = document.getElementById('livekit-remote-badge');
        const localBadge = document.getElementById('livekit-local-badge');

        const isLocalSpeaking = speakers.some(s => s.identity === this.room.localParticipant.identity);
        if (localBadge) localBadge.classList.toggle('is-speaking', isLocalSpeaking);

        const isRemoteSpeaking = speakers.some(s => s.identity !== this.room.localParticipant.identity);
        if (remoteBadge) remoteBadge.classList.toggle('is-speaking', isRemoteSpeaking);
      });

      this.room.on(RoomEvent.TrackMuted, (pub, participant) => {
        this.updateParticipantMuteIcon(participant);
      });
      this.room.on(RoomEvent.TrackUnmuted, (pub, participant) => {
        this.updateParticipantMuteIcon(participant);
      });

      this.room.on(RoomEvent.Connected, () => {
        this.isConnected = true;
        this.isConnecting = false;
        this.updateStatusBadge('connected', 'В сети');
        this.setDockStatusActive(true);
        this.showActiveCallView();
        this.syncRemoteParticipantUI();
      });

      this.room.on(RoomEvent.Reconnecting, () => {
        this.updateStatusBadge('connecting', 'Переподключение...');
      });
      this.room.on(RoomEvent.Reconnected, () => {
        this.updateStatusBadge('connected', 'В сети');
        this.showActiveCallView();
        this.syncRemoteParticipantUI();
      });
      this.room.on(RoomEvent.Disconnected, () => {
        this.handleDisconnected();
      });
    }

    syncRemoteParticipantUI() {
      if (!this.room) return;
      const LivekitClient = window.LivekitClient;

      const remoteVideo = document.getElementById('livekit-remote-video');
      const remotePlaceholder = document.getElementById('livekit-remote-placeholder');
      const remoteNameEl = document.getElementById('livekit-remote-name');
      const remoteBadgeName = document.getElementById('livekit-remote-badge-name');
      const screenshareContainer = document.getElementById('livekit-screenshare-view');
      const screenshareVideo = document.getElementById('livekit-screenshare-video');

      const participants = this.room.remoteParticipants
        ? Array.from(this.room.remoteParticipants.values())
        : [];

      if (participants.length === 0) {
        this.primaryRemoteIdentity = null;
        if (remoteVideo) {
          remoteVideo.style.display = 'none';
          remoteVideo.srcObject = null;
        }
        if (remotePlaceholder) remotePlaceholder.style.display = 'flex';
        if (remoteNameEl) remoteNameEl.textContent = 'Ожидание собеседника...';
        if (remoteBadgeName) remoteBadgeName.textContent = 'Собеседник';
        if (screenshareContainer) {
          screenshareContainer.classList.add('hidden');
          screenshareContainer.hidden = true;
          screenshareContainer.style.display = 'none';
        }
        if (screenshareVideo) screenshareVideo.srcObject = null;
        if (this.isPipActive) this.updatePipVideo();
        return;
      }

      // We have at least 1 remote participant
      const participant = participants[0];
      this.primaryRemoteIdentity = participant.identity;
      this.remoteParticipants.set(participant.identity, participant);

      const displayName = participant.name || (this.isTeacher ? 'Ученик' : 'Преподаватель');
      if (remoteNameEl) remoteNameEl.textContent = displayName;
      if (remoteBadgeName) remoteBadgeName.textContent = displayName;

      const publications = participant.trackPublications
        ? Array.from(participant.trackPublications.values())
        : [];

      // 1. Screenshare track
      const screenPub = publications.find(p => p.source === LivekitClient?.Track?.Source?.ScreenShare && p.track);
      if (screenPub && screenPub.track) {
        this.activeScreenshareIdentity = participant.identity;
        if (screenshareContainer && screenshareVideo) {
          screenshareContainer.classList.remove('hidden');
          screenshareContainer.hidden = false;
          screenshareContainer.style.display = 'flex';
          if (screenshareVideo.srcObject !== screenPub.track.mediaStream) {
            screenPub.track.attach(screenshareVideo);
            screenshareVideo.play().catch(() => {});
          }
        }
      } else {
        this.activeScreenshareIdentity = null;
        if (screenshareContainer) {
          screenshareContainer.classList.add('hidden');
          screenshareContainer.hidden = true;
          screenshareContainer.style.display = 'none';
        }
        if (screenshareVideo) {
          screenshareVideo.srcObject = null;
        }
      }

      // 2. Camera video track
      const camPub = publications.find(p => 
        (p.source === LivekitClient?.Track?.Source?.Camera || p.kind === 'video') && 
        p.source !== LivekitClient?.Track?.Source?.ScreenShare && 
        p.track
      );

      if (camPub && camPub.track) {
        if (camPub.setVideoQuality && LivekitClient?.VideoQuality) {
          camPub.setVideoQuality(LivekitClient.VideoQuality.HIGH);
        }
        if (remoteVideo) {
          if (remoteVideo.srcObject !== camPub.track.mediaStream) {
            camPub.track.attach(remoteVideo);
          }
          remoteVideo.style.display = 'block';
          remoteVideo.play().catch(() => {});
        }
        if (remotePlaceholder) remotePlaceholder.style.display = 'none';
      } else {
        if (remoteVideo) {
          remoteVideo.style.display = 'none';
          remoteVideo.srcObject = null;
        }
        if (remotePlaceholder) remotePlaceholder.style.display = 'flex';
      }

      // 3. Audio track
      const audioPub = publications.find(p => p.kind === 'audio' && p.track);
      if (audioPub && audioPub.track) {
        let audioEl = document.getElementById(`audio-${participant.identity}`);
        if (!audioEl) {
          audioEl = audioPub.track.attach();
          audioEl.id = `audio-${participant.identity}`;
          document.body.appendChild(audioEl);
        }
      }

      // 4. Update PiP if currently active
      if (this.isPipActive) {
        this.updatePipVideo();
      }
    }

    updatePipVideo() {
      const pipVideo = document.getElementById('video-pip-video');
      const pipBadgeName = document.getElementById('video-pip-badge-name');
      if (!pipVideo || !this.room) return;

      const remoteParticipants = this.room.remoteParticipants
        ? Array.from(this.room.remoteParticipants.values())
        : [];

      if (remoteParticipants.length === 0) {
        pipVideo.srcObject = null;
        if (pipBadgeName) pipBadgeName.textContent = 'Ожидание...';
        return;
      }

      const participant = remoteParticipants[0];
      const displayName = participant.name || (this.isTeacher ? 'Ученик' : 'Преподаватель');
      if (pipBadgeName) pipBadgeName.textContent = displayName;

      const LivekitClient = window.LivekitClient;
      const pubs = participant.trackPublications
        ? Array.from(participant.trackPublications.values())
        : [];

      // Check if remote is sharing screen first
      const screenPub = pubs.find(p => p.source === LivekitClient?.Track?.Source?.ScreenShare && p.track);
      if (screenPub && screenPub.track) {
        if (pipVideo.srcObject !== screenPub.track.mediaStream) {
          screenPub.track.attach(pipVideo);
          pipVideo.play().catch(() => {});
        }
        if (pipBadgeName) pipBadgeName.textContent = `${displayName} (Экран)`;
        return;
      }

      // Otherwise show remote camera
      const camPub = pubs.find(p => 
        (p.source === LivekitClient?.Track?.Source?.Camera || p.kind === 'video') && 
        p.source !== LivekitClient?.Track?.Source?.ScreenShare && 
        p.track
      );

      if (camPub && camPub.track) {
        if (pipVideo.srcObject !== camPub.track.mediaStream) {
          camPub.track.attach(pipVideo);
          pipVideo.play().catch(() => {});
        }
        if (pipBadgeName) pipBadgeName.textContent = displayName;
        return;
      }

      pipVideo.srcObject = null;
    }

    handleTrackSubscribed(track, publication, participant) {
      this.syncRemoteParticipantUI();
    }

    handleScreenShareEnded(participant) {
      this.activeScreenshareIdentity = null;
      const screenshareContainer = document.getElementById('livekit-screenshare-view');
      const screenshareVideo = document.getElementById('livekit-screenshare-video');
      if (screenshareVideo) {
        screenshareVideo.srcObject = null;
      }
      if (screenshareContainer) {
        screenshareContainer.classList.add('hidden');
        screenshareContainer.hidden = true;
        screenshareContainer.style.display = 'none';
      }
      this.syncRemoteParticipantUI();
    }

    resetRemoteTile() {
      this.syncRemoteParticipantUI();
    }

    updateParticipantMuteIcon(participant) {
      if (!participant) return;
      const isLocal = participant.identity === this.room?.localParticipant?.identity;
      const micIcon = document.getElementById(isLocal ? 'livekit-local-mic-status' : 'livekit-remote-mic-status');
      if (micIcon) {
        const isMuted = !participant.isMicrophoneEnabled;
        micIcon.className = isMuted ? 'ph-bold ph-microphone-slash text-red-500' : 'ph-bold ph-microphone text-emerald-500';
      }
    }

    /* =====================================================================
       4. CONTROLS (MIC, CAM, SCREENSHARE, TEACHER ADMIN)
       ===================================================================== */

    async toggleMicrophone() {
      if (!this.room?.localParticipant) return;
      this.isAudioMuted = !this.isAudioMuted;
      await this.room.localParticipant.setMicrophoneEnabled(!this.isAudioMuted);

      const micBtn = document.getElementById('livekit-btn-mic');
      const pipMicBtn = document.getElementById('video-pip-mic');

      if (micBtn) {
        micBtn.classList.toggle('is-off', this.isAudioMuted);
        micBtn.innerHTML = this.isAudioMuted
          ? '<i class="ph-bold ph-microphone-slash"></i>'
          : '<i class="ph-bold ph-microphone"></i>';
      }
      if (pipMicBtn) {
        pipMicBtn.classList.toggle('is-off', this.isAudioMuted);
        pipMicBtn.innerHTML = this.isAudioMuted
          ? '<i class="ph-bold ph-microphone-slash"></i>'
          : '<i class="ph-bold ph-microphone"></i>';
      }
      this.updateParticipantMuteIcon(this.room.localParticipant);
    }

    async toggleCamera() {
      if (!this.room?.localParticipant) return;
      this.isVideoMuted = !this.isVideoMuted;
      await this.room.localParticipant.setCameraEnabled(!this.isVideoMuted);

      const camBtn = document.getElementById('livekit-btn-cam');
      const pipCamBtn = document.getElementById('video-pip-cam');

      if (camBtn) {
        camBtn.classList.toggle('is-off', this.isVideoMuted);
        camBtn.innerHTML = this.isVideoMuted
          ? '<i class="ph-bold ph-video-camera-slash"></i>'
          : '<i class="ph-bold ph-video-camera"></i>';
      }
      if (pipCamBtn) {
        pipCamBtn.classList.toggle('is-off', this.isVideoMuted);
        pipCamBtn.innerHTML = this.isVideoMuted
          ? '<i class="ph-bold ph-video-camera-slash"></i>'
          : '<i class="ph-bold ph-video-camera"></i>';
      }
    }

    async toggleScreenShare() {
      if (!this.room?.localParticipant) return;
      const LivekitClient = window.LivekitClient;
      try {
        this.isScreenSharing = !this.isScreenSharing;
        await this.room.localParticipant.setScreenShareEnabled(this.isScreenSharing, {
          audio: false,
          selfBrowserSurface: 'exclude',
          surfaceSwitching: 'include',
          systemAudio: 'exclude',
          resolution: LivekitClient?.ScreenSharePresets?.h1080fps30 || { width: 1920, height: 1080, frameRate: 30 },
          contentHint: 'detail',
          simulcast: false
        });

        const screenBtn = document.getElementById('livekit-btn-screen');
        if (screenBtn) {
          screenBtn.classList.toggle('is-active', this.isScreenSharing);
        }

        if (this.isScreenSharing) {
          const pub = this.room.localParticipant.getTrackPublication(LivekitClient.Track.Source.ScreenShare);
          if (pub?.track?.mediaStreamTrack) {
            pub.track.mediaStreamTrack.onended = () => {
              this.isScreenSharing = false;
              document.getElementById('livekit-btn-screen')?.classList.remove('is-active');
              this.room.localParticipant.setScreenShareEnabled(false).catch(() => {});
              this.syncRemoteParticipantUI();
            };
          }
        } else {
          this.syncRemoteParticipantUI();
        }
      } catch (err) {
        console.warn('[LiveKit] Screen sharing cancelled or denied:', err);
        this.isScreenSharing = false;
        document.getElementById('livekit-btn-screen')?.classList.remove('is-active');
      }
    }

    async teacherMuteStudent() {
      if (!this.isTeacher || !this.room) return;
      if (!this.primaryRemoteIdentity) {
        this.toast('Ученик пока не подключён');
        return;
      }

      const remoteP = this.remoteParticipants.get(this.primaryRemoteIdentity);
      if (!remoteP) return;

      const audioPub = Array.from(remoteP.audioTracks.values())[0];
      if (!audioPub || !audioPub.trackSid) {
        this.toast('Ученик не транслирует микрофон');
        return;
      }

      try {
        const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const resp = await fetch(`/lesson/${this.lessonId}/livekit/admin/mute`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
          body: JSON.stringify({
            identity: this.primaryRemoteIdentity,
            track_sid: audioPub.trackSid,
            muted: true
          })
        });
        const res = await resp.json();
        if (res.success) {
          this.toast('Микрофон ученика выключен');
        } else {
          this.toast(res.error || 'Не удалось заглушить микрофон');
        }
      } catch (e) {
        this.toast('Ошибка вызова админ-метода');
      }
    }

    leaveRoom() {
      if (this.room) {
        this.room.disconnect();
      }
      this.handleDisconnected();
    }

    handleDisconnected() {
      this.isConnected = false;
      this.isConnecting = false;
      this.isAudioMuted = false;
      this.isVideoMuted = false;
      this.isScreenSharing = false;
      this.remoteParticipants.clear();
      this.primaryRemoteIdentity = null;
      this.activeScreenshareIdentity = null;

      document.querySelectorAll('audio[id^="audio-user-"]').forEach(a => a.remove());

      this.updateStatusBadge('idle', 'Не в сети');
      this.setDockStatusActive(false);

      if (this.isPipActive) {
        this.restoreFromPip();
      }

      this.showLobbyView();
    }

    /* =====================================================================
       5. COMPACT FLOATING PIP MODE
       ===================================================================== */

    togglePipMode() {
      if (this.isPipActive) {
        this.restoreFromPip();
      } else {
        this.enterPipMode();
      }
    }

    enterPipMode() {
      const win = document.getElementById('video-window');
      const pip = document.getElementById('video-floating-pip');
      if (!win || !pip) return;

      win.classList.add('hidden');
      win.style.display = 'none';
      pip.classList.remove('hidden');
      this.isPipActive = true;

      this.updatePipVideo();
    }

    restoreFromPip() {
      const win = document.getElementById('video-window');
      const pip = document.getElementById('video-floating-pip');
      if (!win || !pip) return;

      const pipVideo = document.getElementById('video-pip-video');
      if (pipVideo) {
        pipVideo.srcObject = null;
      }

      pip.classList.add('hidden');
      this.isPipActive = false;
      this.openWindow();
      this.syncRemoteParticipantUI();
    }

    closePipToBackground() {
      const pip = document.getElementById('video-floating-pip');
      if (pip) pip.classList.add('hidden');
      this.isPipActive = false;
      this.toast('Звонок продолжается в фоне. Нажмите «Видео» в доке для возврата.');
    }

    setupDraggablePip() {
      const pip = document.getElementById('video-floating-pip');
      if (!pip) return;

      let isDragging = false;
      let startX = 0, startY = 0;
      let initialLeft = 0, initialTop = 0;

      pip.addEventListener('mousedown', (e) => {
        if (e.target.closest('button')) return;
        isDragging = true;
        startX = e.clientX;
        startY = e.clientY;
        const rect = pip.getBoundingClientRect();
        initialLeft = rect.left;
        initialTop = rect.top;

        pip.style.right = 'auto';
        pip.style.bottom = 'auto';
        pip.style.left = `${initialLeft}px`;
        pip.style.top = `${initialTop}px`;
        e.preventDefault();
      });

      window.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        pip.style.left = `${Math.max(10, Math.min(window.innerWidth - pip.offsetWidth - 10, initialLeft + dx))}px`;
        pip.style.top = `${Math.max(10, Math.min(window.innerHeight - pip.offsetHeight - 10, initialTop + dy))}px`;
      });

      window.addEventListener('mouseup', () => {
        isDragging = false;
      });
    }

    /* =====================================================================
       6. UI STATE HELPERS
       ===================================================================== */

    showLobbyView() {
      const lobby = document.getElementById('livekit-view-lobby');
      const call = document.getElementById('livekit-view-call');
      if (lobby) {
        lobby.classList.remove('hidden');
        lobby.hidden = false;
        lobby.style.display = 'flex';
      }
      if (call) {
        call.classList.add('hidden');
        call.hidden = true;
        call.style.display = 'none';
      }
      const joinBtn = document.getElementById('livekit-btn-join');
      if (joinBtn) {
        joinBtn.disabled = false;
        joinBtn.innerHTML = '<i class="ph-bold ph-video-camera"></i> Присоединиться к видеоуроку';
      }
      this.startLobbyPreview();
    }

    showActiveCallView() {
      const lobby = document.getElementById('livekit-view-lobby');
      const call = document.getElementById('livekit-view-call');
      if (lobby) {
        lobby.classList.add('hidden');
        lobby.hidden = true;
        lobby.style.display = 'none';
      }
      if (call) {
        call.classList.remove('hidden');
        call.hidden = false;
        call.style.display = 'flex';
      }
      const screenshareContainer = document.getElementById('livekit-screenshare-view');
      if (screenshareContainer && !this.activeScreenshareIdentity) {
        screenshareContainer.classList.add('hidden');
        screenshareContainer.hidden = true;
        screenshareContainer.style.display = 'none';
      }
    }

    updateStatusBadge(status, label) {
      const badge = document.getElementById('livekit-status-badge');
      if (!badge) return;
      badge.className = `lesson-video-badge status-${status}`;
      badge.innerHTML = `<span class="lesson-video-badge-dot"></span><span>${label}</span>`;
    }

    setDockStatusActive(isActive) {
      const dot = document.getElementById('lesson-os-video-status-dot-dock');
      const topDot = document.getElementById('lesson-os-video-status-dot-top');
      if (dot) dot.classList.toggle('hidden', !isActive);
      if (topDot) topDot.classList.toggle('hidden', !isActive);
      const dockBtn = document.getElementById('dock-icon-video-window');
      if (dockBtn) dockBtn.classList.toggle('is-calling', isActive);
    }

    toast(msg) {
      if (window.toast) {
        window.toast(msg);
      } else {
        const n = document.createElement('div');
        n.className = 'os-toast';
        n.textContent = msg;
        document.body.appendChild(n);
        setTimeout(() => n.remove(), 2600);
      }
    }
  }

  window.lessonLivekit = new LessonLiveKitController();
})();
