// KaraoPi screensaver: shows the logo moving with a selectable animation style
// (bounce, slide, float, pulse), configured via the "screensaver_style" setting.

let x = 0,
  y = 0,
  dirX = 1,
  dirY = 1;
const speed = 1;
const slideSpeed = 1.4;

let animationId = null;
let animationRunning = false;
let floatIntervalId = null;
var fps = 30;

function getScreensaverStyle() {
  const el = document.getElementById("screensaver");
  return (el && el.getAttribute("data-style")) || "bounce";
}

function animateBounce() {
  setTimeout(() => {
    let dvd = document.getElementById("dvd");
    const screenHeight = document.body.clientHeight;
    const screenWidth = document.body.clientWidth;
    const dvdWidth = dvd.clientWidth;
    const dvdHeight = dvd.clientHeight;

    if (y + dvdHeight >= screenHeight || y < 0) {
      dirY *= -1;
    }
    if (x + dvdWidth >= screenWidth || x < 0) {
      dirX *= -1;
    }
    x += dirX * speed;
    y += dirY * speed;
    dvd.style.left = x + "px";
    dvd.style.top = y + "px";
    animationRunning && window.requestAnimationFrame(animateBounce);
  }, 1000 / fps);
}

function animateSlide() {
  setTimeout(() => {
    let dvd = document.getElementById("dvd");
    const screenHeight = document.body.clientHeight;
    const screenWidth = document.body.clientWidth;
    const dvdWidth = dvd.clientWidth;
    const dvdHeight = dvd.clientHeight;

    x += slideSpeed;
    y += slideSpeed;
    // Wrap around instead of bouncing, for a continuous diagonal drift.
    if (x > screenWidth) x = -dvdWidth;
    if (y > screenHeight) y = -dvdHeight;
    dvd.style.left = x + "px";
    dvd.style.top = y + "px";
    animationRunning && window.requestAnimationFrame(animateSlide);
  }, 1000 / fps);
}

function pickRandomFloatPosition() {
  let dvd = document.getElementById("dvd");
  const screenHeight = document.body.clientHeight;
  const screenWidth = document.body.clientWidth;
  const dvdWidth = dvd.clientWidth;
  const dvdHeight = dvd.clientHeight;
  const maxX = Math.max(0, screenWidth - dvdWidth);
  const maxY = Math.max(0, screenHeight - dvdHeight);
  dvd.style.left = Math.round(Math.random() * maxX) + "px";
  dvd.style.top = Math.round(Math.random() * maxY) + "px";
}

function startScreensaver() {
  animationRunning = true;
  x = 0;
  y = 0;
  const style = getScreensaverStyle();

  if (style === "slide") {
    animationId = window.requestAnimationFrame(animateSlide);
  } else if (style === "float") {
    pickRandomFloatPosition();
    floatIntervalId = setInterval(pickRandomFloatPosition, 4000);
  } else if (style === "pulse") {
    // Positioning handled entirely by CSS (#screensaver[data-style="pulse"] #dvd).
  } else {
    animationId = window.requestAnimationFrame(animateBounce);
  }
}

function stopScreensaver() {
  animationRunning = false;
  if (animationId) window.cancelAnimationFrame(animationId);
  if (floatIntervalId) clearInterval(floatIntervalId);
  floatIntervalId = null;
}

