const withBasePath = (path) => `${window.pikaraokeConfig.basePath}${path}`;
let socket = io({ path: window.pikaraokeConfig.socketioPath });
let mouseTimer = null;
let cursorVisible = false;
let nowPlaying = {};
let octopusInstance = null;
let showMenu = false;
let menuButtonVisible = false;
let autoplayConfirmed = false;
let volume = 0.85;
const playbackStartTimeout = 15000;
const bgMediaResumeDelay = 2000;
let isScoreShown = false;
const hasBgVideo = PikaraokeConfig.hasBgVideo;
let currentVideoUrl = null;
let hlsInstance = null;
let hlsRecoveryAttempts = 0;
let idleTime = 0;
let screensaverTimeoutSeconds = PikaraokeConfig.screensaverTimeout;
let bg_playlist = [];
let bgMediaResumeTimeout = null;
let scoreReviews = {
  low: ["Better luck next time!"],
  mid: ["Not bad!"],
  high: ["Great job!"],
};
let isMaster = false;
let uiScale = null;
let clockIntervalId = null;
let splashDomReady = false;
let pendingNowPlaying = null;
const splashRecoveryKey = "pikaraokeSplashRecoveryCount";
let splashRecoveryScheduled = false;
let playbackWatchdogTimer = null;
let stalledPlaybackTimer = null;
let firstVideoFrameRendered = false;
let endingPlaybackId = null;
let mainMediaReady = false;
let backgroundVideoReady = false;
let backgroundMusicReady = false;
let backgroundPlaylistLoaded = false;
let splashReadyEmitted = false;
let bootCoverReleased = false;
let expectedPlaybackDuration = 0;
const prematureEndRecoveryKey = "pikaraokePrematureEndRecoveryCount";

const releaseBootDisplay = () => {
  if (!bootCoverReleased) {
    bootCoverReleased = true;
    document.getElementById("splash-boot-cover")?.classList.add("is-ready");
  }
  // Hiding the local cover must never depend on the master/slave election.
  // Any registered splash may also close the separate boot/update window;
  // only playback-control events remain restricted to the elected master.
  if (!splashReadyEmitted && socket.connected) {
    splashReadyEmitted = true;
    socket.emit("splash_ready");
  }
};

const reportSplashReady = () => {
  if (bootCoverReleased || !splashDomReady || !autoplayConfirmed) return;
  let mediaReady = false;
  if (nowPlaying.now_playing) {
    mediaReady = mainMediaReady;
  } else if (nowPlaying.up_next) {
    mediaReady = true;
  } else {
    const videoReady =
      PikaraokeConfig.disableBgVideo || !hasBgVideo || backgroundVideoReady;
    const musicReady =
      PikaraokeConfig.disableBgMusic ||
      (backgroundPlaylistLoaded && (bg_playlist.length === 0 || backgroundMusicReady));
    mediaReady = videoReady && musicReady;
  }
  if (mediaReady) {
    releaseBootDisplay();
  }
};

const scheduleKioskBootReload = () => {
  const url = new URL(window.location.href);
  if (!url.searchParams.has("kiosk_boot")) return false;

  // Chromium on Raspberry Pi occasionally initializes its video compositor
  // as a black/white surface on the first kiosk navigation. Reload once after
  // the page, socket and media elements have settled, then remove the marker
  // so manual reloads and later reconnects never loop.
  url.searchParams.delete("kiosk_boot");
  setTimeout(() => {
    window.location.replace(url.pathname + url.search + url.hash);
  }, 5000);
  return true;
};

const recoverSplash = (reason) => {
  if (splashRecoveryScheduled) return true;
  const attempts = Number(sessionStorage.getItem(splashRecoveryKey) || 0);
  console.error(`Splash recovery requested: ${reason} (attempt ${attempts + 1})`);
  if (attempts < 2) {
    splashRecoveryScheduled = true;
    sessionStorage.setItem(splashRecoveryKey, String(attempts + 1));
    // Reloading reconstructs the video/HLS pipeline. The server sends its
    // current playback state again as soon as this splash reconnects.
    setTimeout(() => location.reload(), 500);
    return true;
  }
  sessionStorage.removeItem(splashRecoveryKey);
  return false;
};

const clearPlaybackWatchdogs = () => {
  clearTimeout(playbackWatchdogTimer);
  clearTimeout(stalledPlaybackTimer);
  playbackWatchdogTimer = null;
  stalledPlaybackTimer = null;
};

const confirmVideoFrame = () => {
  firstVideoFrameRendered = true;
  mainMediaReady = true;
  clearTimeout(playbackWatchdogTimer);
  clearTimeout(stalledPlaybackTimer);
  sessionStorage.removeItem(splashRecoveryKey);
  reportSplashReady();
};

const watchForDecodedFrame = (video, timeout, reason) => {
  const watchedUrl = currentVideoUrl;
  const watchedPosition = video.currentTime;
  let callbackId = null;
  let frameArrived = false;

  if (typeof video.requestVideoFrameCallback === "function") {
    callbackId = video.requestVideoFrameCallback(() => {
      frameArrived = true;
      if (currentVideoUrl === watchedUrl) confirmVideoFrame();
    });
  }

  return setTimeout(() => {
    if (currentVideoUrl !== watchedUrl || video.ended) return;
    const progressed = video.currentTime > watchedPosition + 0.1;
    const frameMissing = callbackId !== null && !frameArrived;
    if (video.paused || video.readyState < HTMLMediaElement.HAVE_FUTURE_DATA || !progressed || frameMissing) {
      recoverSplash(reason);
    }
  }, timeout);
};

const armPlaybackStartWatchdog = (video) => {
  clearPlaybackWatchdogs();
  firstVideoFrameRendered = false;
  playbackWatchdogTimer = watchForDecodedFrame(
    video,
    playbackStartTimeout,
    "no decoded video frame after playback start"
  );
};

// Browser detection
const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
const isMobileSafari = isSafari && (/iPhone|iPad|iPod/i.test(navigator.userAgent) || navigator.maxTouchPoints > 1);
const isChrome = /chrome/i.test(navigator.userAgent) && !/edg/i.test(navigator.userAgent);
const isFirefox = /firefox/i.test(navigator.userAgent);
const isEdge = /edg/i.test(navigator.userAgent);
const isSupportedBrowser = isSafari || isChrome || isFirefox || isEdge;

const isMediaPlaying = (media) =>
  !!(
    media.currentTime > 0 &&
    !media.paused &&
    !media.ended &&
    media.readyState > 2
  );

const formatTime = (seconds) => {
  if (isNaN(seconds)) {
    return "00:00";
  }
  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  const formattedMinutes = String(minutes).padStart(2, "0");
  const formattedSeconds = String(secs).padStart(2, "0");
  return `${formattedMinutes}:${formattedSeconds}`;
}

const testAutoplayCapability = async () => {
  // A user confirmation remains valid for this dedicated browser profile.
  // The real playback path still handles a rejected play() defensively.
  if (window.localStorage.getItem("karaopiAutoplayConfirmed") === "true") {
    handleConfirmation(false);
    return;
  }

  // Test the permission with an actual unmuted play() call. Starting muted
  // and unmuting afterwards does not reliably exercise Chromium's policy.
  try {
    const testVideo = document.createElement('video');
    testVideo.playsInline = true;
    testVideo.muted = false;
    testVideo.volume = 0.01;
    testVideo.src = withBasePath("/static/video/test_autoplay.mp4");

    // Wait for video to be ready
    await Promise.race([
      new Promise((resolve, reject) => {
      testVideo.onloadeddata = resolve;
      testVideo.onerror = reject;
      }),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error("autoplay capability test timeout")), 5000)
      ),
    ]);

    await testVideo.play();
    testVideo.pause();
    handleConfirmation(false);
  } catch (e) {
    // Autoplay blocked
    console.log("Autoplay error thrown", e);
    $('#permissions-modal').addClass('is-active');
  }
};

const handleConfirmation = (remember = true) => {
  $('#permissions-modal').removeClass('is-active');
  if (remember) {
    window.localStorage.setItem("karaopiAutoplayConfirmed", "true");
  }
  autoplayConfirmed = true;
  updateBackgroundMediaState(true);
  loadNowPlaying();
};

const hideVideo = () => {
  $("#video-container").hide();
}

const endSong = async (reason = null, showScore = false) => {
    const playbackId = currentVideoUrl;
    if (!playbackId || endingPlaybackId === playbackId) {
        console.log("Ignoring duplicate/stale endSong request", reason);
        return;
    }
    endingPlaybackId = playbackId;
    if (showScore && !PikaraokeConfig.disableScore) {
        isScoreShown = true;
        await startScore(withBasePath("/static/"));
        isScoreShown = false;
    }
    currentVideoUrl = null;
    clearPlaybackWatchdogs();
    if (hlsInstance) {
        hlsInstance.destroy();
        hlsInstance = null;
    }
    const video = getVideoPlayer();
    video.pause();
    // It's safer to set src to an empty string to detach the media source
    video.src = "";
    video.removeAttribute("src");
    video.load();
    hideVideo();
    if (isMaster) {
        socket.emit("end_song", { reason: reason, playback_id: playbackId });
    } else {
        console.log("Slave active (read-only): skipping end_song emission");
    }
};

const getBackgroundMusicPlayer = () => document.getElementById('background-music');
const getBackgroundVideoPlayer = () => document.getElementById('bg-video');
const getVideoPlayer = () => $("#video")[0]

const getNextBgMusicSong = () => {
  let currentSong = getBackgroundMusicPlayer().getAttribute('src');
  let nextSong = bg_playlist[0];
  if (currentSong) {
    let currentIndex = bg_playlist.indexOf(currentSong);
    if (currentIndex >= 0 && currentIndex < bg_playlist.length - 1) {
      nextSong = bg_playlist[currentIndex + 1];
    }
  }
  return nextSong;
}

const playBGMusic = async (play) => {
  const audio = getBackgroundMusicPlayer();
  if (play) {
    if (PikaraokeConfig.disableBgMusic) return;
    if (!autoplayConfirmed) return;
    if (bg_playlist.length === 0) return;

    if (!audio.getAttribute('src')) audio.setAttribute('src', getNextBgMusicSong());

    if (isMediaPlaying(audio)) return;
    audio.volume = 0;
    if (audio.readyState <= 2) await audio.load();
    await audio.play().catch(e => console.log("Autoplay blocked (music)"));
    $(audio).animate({ volume: PikaraokeConfig.bgMusicVolume }, 2000);
  } else {
    if (audio) {
      $(audio).animate({ volume: 0 }, 2000, () => audio.pause());
    }
  }
}

const playBGVideo = async (play) => {
  const bgVideo = getBackgroundVideoPlayer();
  const bgVideoContainer = $('#bg-video-container');

  if (play) {
    if (PikaraokeConfig.disableBgVideo) return;
    if (!autoplayConfirmed) return;

    if (isMediaPlaying(bgVideo)) return;
    // Keep the fallback logo/background visible until Chromium has actually
    // decoded and started the background video. Showing the video element
    // earlier can expose a white compositor surface on Raspberry Pi.
    bgVideoContainer.stop(true, true).hide();
    $("#bg-video").attr("src", withBasePath("/stream/bg_video"));
    if (bgVideo.readyState <= 2) await bgVideo.load();
    try {
      await bgVideo.play();
    } catch (error) {
      bgVideoContainer.hide();
      console.log("Autoplay blocked (video)", error);
    }
  } else {
    if (bgVideo) {
      bgVideo.pause();
      bgVideoContainer.stop(true, true).hide();
    }
  }
}

const shouldBackgroundMediaPlay = () => {
  return autoplayConfirmed &&
    !nowPlaying.now_playing &&
    !nowPlaying.up_next;
};

const updateBackgroundMediaState = (immediate = false) => {
  // Clear any pending resume
  if (bgMediaResumeTimeout) {
    clearTimeout(bgMediaResumeTimeout);
    bgMediaResumeTimeout = null;
  }

  if (shouldBackgroundMediaPlay()) {
    if (immediate) {
      playBGMusic(true);
      if (hasBgVideo) playBGVideo(true);
    } else {
      bgMediaResumeTimeout = setTimeout(() => {
        bgMediaResumeTimeout = null;
        if (shouldBackgroundMediaPlay()) {
          playBGMusic(true);
          if (hasBgVideo) playBGVideo(true);
        }
      }, bgMediaResumeDelay);
    }
  } else {
    playBGMusic(false);
    playBGVideo(false);
  }
};

const flashNotification = (message, categoryClass) => {
  const sn = $("#splash-notification");
  if (sn.html()) return;
  sn.html(message);
  sn.addClass(categoryClass);
  sn.fadeIn();
  setTimeout(() => {
    sn.fadeOut();
    setTimeout(() => {
      sn.html("");
      sn.removeClass(categoryClass);
    }, 450);
  }, 3000);
}

const setupScreensaver = () => {
  if (screensaverTimeoutSeconds > 0) {
    setInterval(() => {
      let screensaver = document.getElementById('screensaver');
      let video = getVideoPlayer();
      if (isMediaPlaying(video) || cursorVisible) {
        idleTime = 0;
      }
      if (idleTime >= screensaverTimeoutSeconds) {
        if (screensaver.style.visibility === 'hidden') {
          screensaver.style.visibility = 'visible';
          playBGVideo(false);
          startScreensaver(); // depends on upstream screensaver.js import
        }
        if (idleTime > screensaverTimeoutSeconds + 36000) idleTime = screensaverTimeoutSeconds;
      } else {
        if (screensaver.style.visibility === 'visible') {
          screensaver.style.visibility = 'hidden';
          stopScreensaver(); // depends on upstream screensaver.js import
          updateBackgroundMediaState(true);
        }
      }
      idleTime++;
    }, 1000)
  }
}

/**
 * Tente de manière robuste de lancer la lecture d'un élément vidéo.
 * Gère les erreurs d'autoplay en réessayant périodiquement.
 *
 * @param {HTMLVideoElement} videoElement - L'élément vidéo à lancer.
 * @returns {Promise<void>} Une promesse qui se résout lorsque la lecture commence, ou est rejetée après plusieurs échecs.
 */
async function playVideoRobustly(videoElement) {
    const maxRetries = 3;
    let lastError = null;

    for (let i = 0; i < maxRetries; i++) {
        try {
            // Calling play immediately lets Chromium start fetching and
            // decoding instead of polling readyState every 500 ms.
            await Promise.race([
                videoElement.play(),
                new Promise((_, reject) =>
                    setTimeout(() => reject(new Error("playback start timeout")), 15000)
                ),
            ]);
            console.log('Video playback started successfully.');
            return;
        } catch (error) {
            lastError = error;
            console.warn(`Attempt ${i + 1} to play video failed:`, error.name, error.message);
            if (error.name === "NotAllowedError") break;
            await new Promise(resolve => {
                const done = () => {
                    videoElement.removeEventListener("canplay", done);
                    videoElement.removeEventListener("error", done);
                    resolve();
                };
                videoElement.addEventListener("canplay", done, { once: true });
                videoElement.addEventListener("error", done, { once: true });
                setTimeout(done, 750);
            });
        }
    }

    const detail = lastError ? `${lastError.name}: ${lastError.message}` : "unknown error";
    throw new Error(`Failed to play video after ${maxRetries} attempts (${detail})`);
}

const handlePlaybackStartFailure = (error, recoveryReason) => {
  // Do not enter the reload recovery loop when Chromium explicitly blocked
  // autoplay. Keep the current song pending and ask for one real interaction.
  if (String(error && error.message).includes("NotAllowedError")) {
    window.localStorage.removeItem("karaopiAutoplayConfirmed");
    autoplayConfirmed = false;
    currentVideoUrl = null;
    $('#permissions-modal').addClass('is-active');
    return true;
  }
  return recoverSplash(recoveryReason);
};

const handleNowPlayingUpdate = (np) => {
  nowPlaying = np;
  if (np.now_playing) {
    if (np.now_playing_cover) {
      $("#splash-now-playing-cover")
        .attr("src", withBasePath("/cover/" + np.now_playing_cover))
        .show();
    } else {
      $("#splash-now-playing-cover").hide().removeAttr("src");
    }

    // Handle updating now playing HTML
    let nowPlayingHtml = `<span>${np.now_playing}</span> `;
    if (np.now_playing_transpose !== 0) {
      nowPlayingHtml += `<span class='is-size-6 has-text-success'><b>Key</b>: ${getSemitonesLabel(np.now_playing_transpose)} </span>`;
    }
    $("#now-playing-song").html(nowPlayingHtml);
    $("#now-playing-singer").html(np.now_playing_user);
    $("#now-playing").fadeIn();
  } else {
    $("#splash-now-playing-cover").hide().removeAttr("src");
    $("#now-playing").fadeOut();
  }
  if (np.up_next) {
    $("#up-next-song").html(np.up_next);
    $("#up-next-singer").html(np.next_user);
    $("#up-next").fadeIn();
  } else {
    $("#up-next").fadeOut();
  }

  // Update bg music and video state
  if (np.now_playing || np.up_next) {
    idleTime = 0;
  }
  updateBackgroundMediaState();

  const video = getVideoPlayer();

  if (np.now_playing_url && np.now_playing_url !== currentVideoUrl) {
    currentVideoUrl = np.now_playing_url;
    endingPlaybackId = null;
    hlsRecoveryAttempts = 0;
    expectedPlaybackDuration = Number(np.now_playing_duration) || 0;
    const streamUrl = np.now_playing_url;
    const resumePosition = Number(np.now_playing_position) || 0;

    video.pause();
    if (resumePosition > 1) {
      video.addEventListener("loadedmetadata", () => {
        if (currentVideoUrl === streamUrl && video.currentTime < resumePosition - 2) {
          console.log("Restoring recovered playback position:", resumePosition);
          video.currentTime = resumePosition;
        }
      }, { once: true });
    }
    // Subtitle rendering is tied to the media identity. Rebuilding its WASM
    // canvas on every queue/volume update can interrupt the Pi compositor.
    if (octopusInstance) {
      octopusInstance.dispose();
      octopusInstance = null;
    }
    const subtitleUrl = np.now_playing_subtitle_url;
    if (subtitleUrl && video) {
      const options = {
        video: video,
        subUrl: subtitleUrl,
        fonts: [
          withBasePath("/static/fonts/Arial.ttf"),
          withBasePath("/static/fonts/DroidSansFallback.ttf"),
        ],
        debug: false,
        workerUrl: withBasePath("/static/js/subtitles-octopus-worker.js")
      };
      try {
        octopusInstance = new SubtitlesOctopus(options);
        if (uiScale) {
          const canvas = video.parentNode.querySelector('canvas');
          if (canvas) {
            canvas.style.transform = `scale(${uiScale})`;
            canvas.style.transformOrigin = 'bottom center';
          }
        }
      } catch (e) { console.error(e); }
    }
    if (hlsInstance) {
      hlsInstance.destroy();
      hlsInstance = null;
    }
    video.removeAttribute("src");
    $("#video-source").removeAttr("src");

    if (streamUrl.endsWith('.m3u8')) {
      const useNativeHLS = video.canPlayType('application/vnd.apple.mpegurl') && !isChrome && !isEdge && !isMobileSafari;
      if (useNativeHLS) {
        video.src = streamUrl;
        video.load();
        playVideoRobustly(video).catch(e => {
            console.error("Could not start native HLS playback:", e);
            if (!handlePlaybackStartFailure(e, "native HLS failed to start")) {
              endSong("failed to start");
            }
        });
      } else {
        hlsInstance = new Hls({
          startPosition: 0,
          startFragPrefetch: true,
          maxBufferLength: 12,
          backBufferLength: 30,
        });
        // MEDIA_ATTACHED is too early on slower devices. Wait until the
        // manifest has been parsed and HLS has started filling the media.
        hlsInstance.once(Hls.Events.MANIFEST_PARSED, function () {
          console.log("HLS.js manifest parsed, attempting to play.");
          playVideoRobustly(video).catch(e => {
              console.error("Could not start HLS.js playback:", e);
              if (!handlePlaybackStartFailure(e, "HLS.js failed to start")) {
                endSong("failed to start");
              }
          });
        });
        hlsInstance.on(Hls.Events.ERROR, function (_event, data) {
          if (currentVideoUrl !== streamUrl || endingPlaybackId === streamUrl) return;
          if (data.fatal) {
            console.error("Fatal HLS error:", data);
            hlsRecoveryAttempts += 1;
            if (data.type === Hls.ErrorTypes.NETWORK_ERROR && hlsRecoveryAttempts <= 2) {
              hlsInstance.startLoad();
            } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR && hlsRecoveryAttempts <= 2) {
              hlsInstance.recoverMediaError();
            } else if (!recoverSplash(`fatal HLS error: ${data.type}`)) {
              endSong("fatal HLS error");
            }
          }
        });
        hlsInstance.attachMedia(video);
        hlsInstance.loadSource(streamUrl);
      }
    } else {
      // Pour les non-HLS (MP4, etc.)
      video.src = streamUrl;
      video.load();
      playVideoRobustly(video).catch(e => {
          console.error("Could not start video playback:", e);
          if (!handlePlaybackStartFailure(e, "video failed to start")) {
            endSong("failed to start");
          }
      });
    }

    if (volume !== np.volume) {
      volume = np.volume;
      video.volume = volume;
    }

    armPlaybackStartWatchdog(video);

    const duration = $("#duration");
    if (np.now_playing_duration) {
      duration.text(`/${formatTime(np.now_playing_duration)}`);
      duration.show();
    } else {
      duration.hide();
    }

  }
}

async function loadNowPlaying() {
  const data = await $.get(withBasePath("/now_playing"));
  handleNowPlayingUpdate(JSON.parse(data));
}

const setupOverlayMenus = () => {
  if (PikaraokeConfig.hideOverlay) {
    $('#bottom-container').hide();
    $('#top-container').hide();
  }
  $("#menu a").fadeOut(); // start hidden
  const triggerInactivity = () => {
    mouseTimer = null;
    document.body.style.cursor = 'none';
    cursorVisible = false;
    $("#menu a").fadeOut();
    if (PikaraokeConfig.showSplashClock) {
      setTimeout(() => {
        if (!cursorVisible) $("#clock").fadeIn();
      }, 1000);
    }
    menuButtonVisible = false;
  };

  document.onmousemove = function () {
    if (mouseTimer) window.clearTimeout(mouseTimer);
    if (!cursorVisible) {
      document.body.style.cursor = 'default';
      cursorVisible = true;
    }
    if (!menuButtonVisible) {
      $("#menu a").fadeIn();
      $("#clock").hide();
      menuButtonVisible = true;
    }
    mouseTimer = window.setTimeout(triggerInactivity, 5000);
  };

  // Set initial state to hidden
  triggerInactivity();
  $('#menu a').click(function () {
    if (showMenu) {
      $('#menu-container').hide();
      $('#menu-container iframe').attr('src', '');
      showMenu = false;
    } else {
      setUserCookie();
      $("#menu-container").show();
      $("#menu-container iframe").attr("src", withBasePath("/"));
      showMenu = true;
    }
  });
  $('#menu-background').click(function () {
    if (showMenu) {
      $(".navbar-burger").click();
    }
  });
}

const setupVideoPlayer = () => {
  $('#video-container').hide();
  const video = getVideoPlayer();
  video.addEventListener("play", () => {
    $("#video-container").show();
    if (typeof video.requestVideoFrameCallback !== "function") {
      confirmVideoFrame();
    }
    if (isMaster) {
      const playbackId = currentVideoUrl;
      setTimeout(() => {
        if (playbackId && currentVideoUrl === playbackId && !video.paused) {
          socket.emit("start_song", { playback_id: playbackId });
        }
      }, 1200);
    }
  });

  // Master reports playback position to server
  setInterval(() => {
    if (isMaster && isMediaPlaying(video)) {
      socket.emit("playback_position", {
        position: video.currentTime,
        playback_id: currentVideoUrl,
      });
    }
  }, 1000);

  video.addEventListener("ended", () => {
    const remaining = expectedPlaybackDuration - video.currentTime;
    const tolerance = Math.max(5, expectedPlaybackDuration * 0.025);
    if (expectedPlaybackDuration > 0 && remaining > tolerance) {
      const attempts = Number(sessionStorage.getItem(prematureEndRecoveryKey) || 0);
      console.error(
        `Firefox/media pipeline ended ${remaining.toFixed(1)}s too early (attempt ${attempts + 1})`
      );
      if (attempts < 2) {
        sessionStorage.setItem(prematureEndRecoveryKey, String(attempts + 1));
        setTimeout(() => location.reload(), 400);
      } else {
        sessionStorage.removeItem(prematureEndRecoveryKey);
        endSong("premature browser end", false);
      }
      return;
    }
    sessionStorage.removeItem(prematureEndRecoveryKey);
    endSong("complete", true);
  });
  video.addEventListener("timeupdate", () => {
    $("#current").text(formatTime(video.currentTime));
    // Once a recovered stream has played a meaningful interval, a later
    // decoder incident may use the recovery budget again.
    if (video.currentTime > Math.min(30, expectedPlaybackDuration * 0.25)) {
      sessionStorage.removeItem(prematureEndRecoveryKey);
    }
  });
  const monitorPlaybackStall = (event) => {
    if (!currentVideoUrl || video.ended || splashRecoveryScheduled) return;
    clearTimeout(stalledPlaybackTimer);
    stalledPlaybackTimer = watchForDecodedFrame(
      video,
      8000,
      `video remained ${event.type}`
    );
  };
  video.addEventListener("waiting", monitorPlaybackStall);
  video.addEventListener("stalled", monitorPlaybackStall);
  $("#video source")[0].addEventListener("error", (e) => {
    if (isMediaPlaying(video)) {
      endSong("error while playing");
    }
  });
}

const setupBackgroundVideoPlayer = () => {
  const bgVideo = getBackgroundVideoPlayer();
  const container = $("#bg-video-container");
  container.hide();
  bgVideo.addEventListener("playing", () => {
    backgroundVideoReady = true;
    if (shouldBackgroundMediaPlay()) container.fadeIn(1000);
    reportSplashReady();
  });
  bgVideo.addEventListener("error", (event) => {
    console.error("Background video failed:", event);
    container.stop(true, true).hide();
  });
  bgVideo.addEventListener("stalled", () => {
    if (!isMediaPlaying(bgVideo)) container.stop(true, true).hide();
  });
};

const setupBackgroundMusicPlayer = () => {
  $.get(withBasePath("/bg_playlist"), function (data) {
    if (data) bg_playlist = data;
    backgroundPlaylistLoaded = true;
    updateBackgroundMediaState(true);
    reportSplashReady();
  });
  const bgMusic = getBackgroundMusicPlayer();
  bgMusic.addEventListener("playing", () => {
    backgroundMusicReady = true;
    reportSplashReady();
  });
  bgMusic.addEventListener("ended", async () => {
    bgMusic.setAttribute('src', getNextBgMusicSong());
    await bgMusic.load();
    await bgMusic.play();
  });
}

const handleUnsupportedBrowser = () => {
  if (!isSupportedBrowser) {
    let modalContents = document.getElementById("permissions-modal-content");
    let warningMessage = document.createElement("p");
    warningMessage.classList.add("notification", "is-warning");
    warningMessage.innerHTML =
      PikaraokeConfig.translations.unsupportedBrowser;
    modalContents.prepend(warningMessage);
  }
}

const updateClock = () => {
  const el = document.getElementById('clock');
  if (el) {
    el.textContent = new Date().toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      hour12: PikaraokeConfig.clockFormat === '12h',
    });
  }
};

const startClock = () => {
  if (clockIntervalId) return;
  updateClock();
  clockIntervalId = setInterval(updateClock, 1000);
}

const stopClock = () => {
  if (!clockIntervalId) return;
  clearInterval(clockIntervalId);
  clockIntervalId = null;
}

const toggleBGMedia = (configKey, playFn, disabled) => {
  PikaraokeConfig[configKey] = disabled;
  disabled ? playFn(false) : shouldBackgroundMediaPlay() && playFn(true);
};

const PREFERENCE_EFFECTS = {
  disable_bg_video:    (v) => toggleBGMedia("disableBgVideo", playBGVideo, v),
  disable_bg_music:    (v) => toggleBGMedia("disableBgMusic", playBGMusic, v),
  disable_score:       (v) => { PikaraokeConfig.disableScore = v; },
  show_splash_clock:   (v) => {
    PikaraokeConfig.showSplashClock = v;
    v ? startClock() : (stopClock(), $("#clock").hide());
  },
  clock_format:        (v) => {
    PikaraokeConfig.clockFormat = v;
    updateClock();
  },
  hide_overlay:        (v) => {
    PikaraokeConfig.hideOverlay = v;
    $("#bottom-container, #top-container").toggle(!v);
  },
  hide_url:            (v) => { $("#qr-code, #screensaver-qr").toggle(!v); },
  bg_music_volume:     (v) => {
    PikaraokeConfig.bgMusicVolume = v;
    const player = getBackgroundMusicPlayer();
    if (isMediaPlaying(player)) $(player).animate({ volume: v }, 1000);
  },
  screensaver_timeout: (v) => {
    screensaverTimeoutSeconds = v;
    PikaraokeConfig.screensaverTimeout = v;
  },
};

const parsePreferenceValue = (value) => {
  if (typeof value !== "string") return value;
  if (value === "True") return true;
  if (value === "False") return false;
  const num = Number(value);
  return !isNaN(num) && value.trim() !== "" ? num : value;
};

const applyPreferenceUpdate = (data) => {
  const effect = PREFERENCE_EFFECTS[data.key];
  if (effect) effect(parsePreferenceValue(data.value));
};

const applyPreferencesReset = (defaults) => {
  Object.entries(defaults).forEach(([key, value]) => applyPreferenceUpdate({ key, value }));
};

const setupSocketEvents = () => {
  socket.on('connect', () => {
    console.log('Socket connected');
    socket.emit("register_splash");
  });
  socket.on('splash_role', (role) => {
    isMaster = (role === "master");
    console.log("Splash role assigned:", role, isMaster ? "(Master active)" : "(Slave active - read-only)");
    reportSplashReady();
  });
  socket.on('connect_error', (error) => {
    console.error('Connection error:', error);
    flashNotification(PikaraokeConfig.translations.socketConnectionLost, "is-danger");
  });
  socket.on('disconnect', (reason) => {
    console.warn('Socket disconnected:', reason);
    flashNotification(PikaraokeConfig.translations.socketConnectionLost, "is-danger");
  });
  socket.on('pause', () => {
    const video = getVideoPlayer();
    const currVolume = video.volume;
    if (!video.paused) {
      $(video).animate({ volume: 0 }, 1000, () => {
        video.pause();
        video.volume = currVolume;
      });
    }
  });
  socket.on('play', () => {
    const video = getVideoPlayer();
    const currVolume = video.volume;
    if (video.paused) {
      video.play();
      video.volume = 0;
      $(video).animate({ volume: currVolume }, 1000);
    }
  });
  socket.on('skip', (reason) => {
    const video = getVideoPlayer();
    const currVolume = video.volume;
    if (isMediaPlaying(video)) {
      $(video).animate({ volume: 0 }, 1000, () => {
        video.pause();
        video.volume = currVolume;
        hideVideo();
      });
    } else {
      video.pause();
      hideVideo();
    }
  });
  socket.on('volume', (val) => {
    const video = getVideoPlayer();
    if (val === "up") {
      video.volume = Math.min(1, video.volume + 0.1);
    } else if (val === "down") {
      video.volume = Math.max(0, video.volume - 0.1);
    } else {
      video.volume = val;
    }
  });
  socket.on('restart', () => {
    const video = getVideoPlayer();
    video.currentTime = 0;
    if (video.paused) video.play();
  });
  socket.on("notification", (data) => {
    const notification = data.split("::");
    const message = notification[0];
    const categoryClass = notification.length > 1 ? notification[1] : "is-primary";
    flashNotification(message, categoryClass);
    if (isMaster) {
      socket.emit("clear_notification");
    }
  });
  socket.on("now_playing", (state) => {
    if (splashDomReady) {
      handleNowPlayingUpdate(state);
    } else {
      pendingNowPlaying = state;
    }
  });
  socket.on("preferences_update", applyPreferenceUpdate);
  socket.on("preferences_reset", applyPreferencesReset);
  socket.on("score_phrases_update", (phrases) => { scoreReviews = phrases; });
  socket.on("force_reload_splash", () => { location.reload(); });

  socket.on("playback_position", (position) => {
    if (!isMaster) {
      const video = getVideoPlayer();
      if (isMediaPlaying(video)) {
        if (Math.abs(video.currentTime - position) > 2) {
          console.log("Slave drifting, syncing position to:", position);
          video.currentTime = position;
        }
      }
    }
  });
}

const handleSocketRecovery = () => {
  // A socket may disconnect if the tab is backgrounded for a while
  // Reconnect and configure event listeners when tab becomes visible again
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === 'visible') {
      autoplayConfirmed && loadNowPlaying();
      if (!socket.connected) {
        socket = io({ path: window.pikaraokeConfig.socketioPath });
        setupSocketEvents();
      }
    }
  });
}

const setupUIScaling = () => {
  const urlParams = new URLSearchParams(window.location.search);
  const rawScale = urlParams.get('scale');
  if (!rawScale) return;
  uiScale = parseFloat(rawScale) || 1;

  const scaleTargets = [
    { selector: '#logo-container img.logo', origin: null },
    { selector: '#top-container', origin: 'top right' },
    { selector: '#ap-container', origin: 'top left' },
    { selector: '#qr-code', origin: 'bottom left' },
    { selector: '#up-next', origin: 'bottom right' },
    { selector: '#dvd', origin: null },
    { selector: '#your-score-text', origin: null },
    { selector: '#score-number-text', origin: null },
    { selector: '#score-review-text', origin: null },
    { selector: '#splash-notification', origin: 'top left' },
    { selector: '#clock', origin: 'top left' },
  ];

  scaleTargets.forEach(({ selector, origin }) => {
    const el = document.querySelector(selector);
    if (el) {
      el.style.transform = `scale(${uiScale})`;
      if (origin) el.style.transformOrigin = origin;
    }
  });
}

// Document ready procedures

$(function () {
  // During the hidden warm-up pass, do not start audio/video or UI effects.
  // Chromium only initializes its renderer, then reloads into the real splash.
  if (scheduleKioskBootReload()) return;
  // Setup various features and listeners
  setupUIScaling();
  if (PikaraokeConfig.showSplashClock) startClock();
  setupScreensaver();
  setupOverlayMenus();
  setupVideoPlayer();
  setupBackgroundVideoPlayer();
  setupBackgroundMusicPlayer();
  splashDomReady = true;
  if (pendingNowPlaying) {
    handleNowPlayingUpdate(pendingNowPlaying);
    pendingNowPlaying = null;
  }

  // Handle browser compatibility
  handleUnsupportedBrowser();
  testAutoplayCapability();
  reportSplashReady();
  // A missing/corrupt optional background asset must not leave the diagnostic
  // boot window permanently above an otherwise usable splash.
  setTimeout(() => {
    if (!bootCoverReleased) {
      console.warn("Splash media readiness timed out; releasing boot display");
      releaseBootDisplay();
    }
  }, 20000);
});


// Setup sockets and recovery outside of document ready to prevent race conditions
setupSocketEvents();
handleSocketRecovery();

// Fallback: if socket connected before listeners were attached, register now
if (socket.connected) {
  console.log('Socket already connected, registering splash...');
  socket.emit("register_splash");
}
