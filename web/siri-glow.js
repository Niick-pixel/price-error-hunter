/* SiriGlow - full-screen edge glow rendered as a signed distance field.
 *
 * Not a bordered element. Every pixel computes its distance to the nearest
 * edge of a superellipse rounded-rect matching the viewport, and intensity is
 * exp(-d / lambda). Because the falloff is analytic there is no blur to
 * rasterize, so the bloom is exact and free - the whole thing is one fragment
 * shader in a single GPU layer, which is what keeps it at 60fps while being
 * driven by audio.
 *
 * Colour is sampled by position along the PERIMETER, not by angle from centre.
 * On a wide viewport an angular sweep bunches colour into the short edges;
 * arc-length parameterisation keeps the lobes evenly paced all the way round.
 *
 * Usage:
 *   const glow = new SiriGlow();
 *   glow.state = "listening";
 *   glow.amplitude = 0.6;          // or glow.listenToMic() after a gesture
 *   glow.destroy();
 *
 * No dependencies, no build step, works from file://.
 */
(function (global) {
  "use strict";

  var VERT = [
    "attribute vec2 aPos;",
    "void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }"
  ].join("\n");

  var FRAG = [
    "precision highp float;",

    "uniform vec2  uRes;",       // drawing buffer size, device px
    "uniform vec4  uInset;",     // safe area: top, right, bottom, left
    "uniform float uRadius;",
    "uniform float uPnorm;",
    "uniform float uLambda;",
    "uniform vec3  uBloomW;",    // layer weights
    "uniform vec3  uBloomS;",    // layer sigma multipliers
    "uniform float uOpacity;",
    "uniform float uHairline;",
    "uniform float uNoise;",
    "uniform float uLobeGain;",
    "uniform float uLobeWidth;",
    "uniform vec3  uLobePos;",
    "uniform float uTime;",
    "uniform float uP3;",
    "uniform vec3  uStop0;",
    "uniform vec3  uStop1;",
    "uniform vec3  uStop2;",
    "uniform vec3  uStop3;",

    "const float PI = 3.14159265359;",
    "const float HPI = 1.57079632679;",

    // p-norm distance. p = 2 is a circle; higher p squares the corner off into
    // a superellipse, which is what gives continuous curvature instead of the
    // curvature discontinuity you get where a circular arc meets a straight.
    "float pnorm2(vec2 v, float p){",
    "  return pow(pow(max(v.x,0.0), p) + pow(max(v.y,0.0), p), 1.0/p);",
    "}",

    "float sdBox(vec2 p, vec2 b, float r, float pn){",
    "  vec2 q = abs(p) - b + r;",
    "  return min(max(q.x, q.y), 0.0) + pnorm2(max(q, vec2(0.0)), pn) - r;",
    "}",

    // Arc length from top-centre, clockwise, normalised to 0..1.
    "float perimeterT(vec2 p, vec2 b, float r){",
    "  float w = max(b.x - r, 0.0);",
    "  float h = max(b.y - r, 0.0);",
    "  float arc = HPI * r;",
    "  float P = 4.0*w + 4.0*h + 4.0*arc;",
    "  float s;",
    "  if (p.x >= w && p.y >= h) {",              // top-right corner
    "    float th = atan(p.y - h, p.x - w);",
    "    s = w + (HPI - th) * r;",
    "  } else if (p.x >= w && p.y <= -h) {",      // bottom-right
    "    float th = atan(p.y + h, p.x - w);",
    "    s = w + arc + 2.0*h + (-th) * r;",
    "  } else if (p.x <= -w && p.y <= -h) {",     // bottom-left
    "    float th = atan(p.y + h, p.x + w);",
    "    s = 3.0*w + 2.0*h + 2.0*arc + (-HPI - th) * r;",
    "  } else if (p.x <= -w && p.y >= h) {",      // top-left
    "    float th = atan(p.y - h, p.x + w);",
    "    s = 3.0*w + 4.0*h + 3.0*arc + (PI - th) * r;",
    "  } else if (p.y >= h) {",                   // top edge
    "    s = (p.x >= 0.0) ? p.x : (P + p.x);",
    "  } else if (p.x >= w) {",                   // right edge
    "    s = w + arc + (h - p.y);",
    "  } else if (p.y <= -h) {",                  // bottom edge
    "    s = w + arc + 2.0*h + arc + (w - p.x);",
    "  } else {",                                 // left edge
    "    s = 3.0*w + 2.0*h + 3.0*arc + (p.y + h);",
    "  }",
    "  return fract(s / max(P, 1.0));",
    "}",

    "vec3 stopAt(int i){",
    "  if(i <= 0) return uStop0;",
    "  if(i == 1) return uStop1;",
    "  if(i == 2) return uStop2;",
    "  return uStop3;",
    "}",

    // Interpolating in OKLCH keeps chroma up. A straight sRGB or OKLab lerp
    // from magenta to cyan runs through the neutral axis and greys out at the
    // midpoint; taking the short way round the hue circle never desaturates.
    "vec3 lchMix(vec3 a, vec3 b, float t){",
    "  float dh = mod(b.z - a.z + 540.0, 360.0) - 180.0;",
    "  return vec3(mix(a.x, b.x, t), mix(a.y, b.y, t), a.z + dh * t);",
    "}",

    "vec3 lch2lab(vec3 c){",
    "  float h = radians(c.z);",
    "  return vec3(c.x, c.y * cos(h), c.y * sin(h));",
    "}",

    "vec3 lab2lrgb(vec3 lab){",
    "  float l_ = lab.x + 0.3963377774*lab.y + 0.2158037573*lab.z;",
    "  float m_ = lab.x - 0.1055613458*lab.y - 0.0638541728*lab.z;",
    "  float s_ = lab.x - 0.0894841775*lab.y - 1.2914855480*lab.z;",
    "  float l = l_*l_*l_; float m = m_*m_*m_; float s = s_*s_*s_;",
    "  return vec3(",
    "     4.0767416621*l - 3.3077115913*m + 0.2309699292*s,",
    "    -1.2684380046*l + 2.6097574011*m - 0.3413193965*s,",
    "    -0.0041960863*l - 0.7034186147*m + 1.7076147010*s);",
    "}",

    // Linear sRGB -> linear Display P3. Only applied when the drawing buffer
    // is actually P3, otherwise the wide primaries would be over-saturated.
    "vec3 lrgb2lp3(vec3 c){",
    "  return vec3(",
    "    0.8224621*c.r + 0.1775380*c.g + 0.0000000*c.b,",
    "    0.0331941*c.r + 0.9668058*c.g + 0.0000000*c.b,",
    "    0.0170827*c.r + 0.0723974*c.g + 0.9105199*c.b);",
    "}",

    "float hash(vec2 p){",
    "  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);",
    "}",

    "void main(){",
    "  vec2 fc = gl_FragCoord.xy;",
    "  vec2 lo = vec2(uInset.w, uInset.z);",
    "  vec2 hi = vec2(uRes.x - uInset.y, uRes.y - uInset.x);",
    "  vec2 c  = 0.5 * (lo + hi);",
    "  vec2 b  = max(0.5 * (hi - lo), vec2(1.0));",
    "  vec2 p  = fc - c;",

    "  float r = min(uRadius, min(b.x, b.y));",
    "  float ad = abs(sdBox(p, b, r, uPnorm));",

    // Three additive bloom layers. Summing exponentials IS plus-lighter here,
    // done analytically rather than by blurring three buffers.
    "  float g = uBloomW.x * exp(-ad / max(uLambda * uBloomS.x, 1.0))",
    "          + uBloomW.y * exp(-ad / max(uLambda * uBloomS.y, 1.0))",
    "          + uBloomW.z * exp(-ad / max(uLambda * uBloomS.z, 1.0));",

    "  float t = perimeterT(p, b, r);",

    "  float f = t * 4.0;",
    "  int i0 = int(floor(f));",
    "  float k = f - float(i0);",
    "  int i1 = i0 + 1; if (i1 > 3) i1 = 0;",
    "  vec3 col = lchMix(stopAt(i0), stopAt(i1), k);",

    // Three lobes drifting at unrelated rates, mixed sequentially so the hue
    // never averages through grey. Their envelopes beat against each other,
    // which is what stops it reading as one rigidly rotating gradient.
    "  float gain = 1.0;",
    "  for (int i = 0; i < 3; i++) {",
    "    float lp = (i == 0) ? uLobePos.x : ((i == 1) ? uLobePos.y : uLobePos.z);",
    "    float dt = abs(t - lp); dt = min(dt, 1.0 - dt);",
    "    float wq = exp(-(dt*dt) / (2.0 * max(uLobeWidth*uLobeWidth, 1e-5)));",
    "    vec3 lc = (i == 0) ? uStop0 : ((i == 1) ? uStop2 : uStop3);",
    "    col = lchMix(col, lc, wq * 0.85);",
    "    gain += uLobeGain * wq;",
    "  }",

    "  vec3 lin = max(lab2lrgb(lch2lab(col)), vec3(0.0));",

    // Specular hairline: brightest where curvature is highest, i.e. corners.
    "  vec2 q = abs(p) - b + r;",
    "  float corner = clamp(min(q.x, q.y) / max(r, 1.0), 0.0, 1.0);",
    "  float hair = exp(-ad / 1.25) * (0.30 + 0.70 * corner) * uHairline;",

    "  vec3 outLin = (lin * g * gain + vec3(hair)) * uOpacity;",
    "  if (uP3 > 0.5) outLin = lrgb2lp3(outLin);",

    "  vec3 srgb = pow(max(outLin, vec3(0.0)), vec3(1.0 / 2.2));",

    // 8-bit output bands visibly across a soft exponential falloff, worst on
    // OLED at low brightness. A little monochrome noise dithers it away.
    "  srgb += (hash(fc + fract(uTime) * 137.0) - 0.5) * uNoise;",

    "  float a = clamp(max(max(srgb.r, srgb.g), srgb.b), 0.0, 1.0);",
    "  gl_FragColor = vec4(clamp(srgb, 0.0, 1.0) * a, a);",  // premultiplied
    "}"
  ].join("\n");

  // Palette in OKLCH (L 0..1, C, H degrees). Deliberately full-spectrum - the
  // colour is the point of this effect - but the chroma is pulled back from the
  // original so it tints the edge of the screen rather than dominating it.
  var DEFAULT_STOPS = [
    [0.70, 0.17, 340],   // magenta
    [0.78, 0.13,  45],   // coral / amber
    [0.60, 0.16, 285],   // indigo / violet
    [0.80, 0.11, 200]    // cyan
  ];

  var DEFAULTS = {
    lambda: 60,
    radius: 55,
    pnorm: 4.5,
    bloomWeights: [0.40, 0.70, 1.00],
    bloomSigmas: [1.0, 0.36, 0.08],   // ~ 50 / 18 / 4 px at lambda 60
    hairline: 0.9,
    noise: 0.02,
    lobeGain: 0.55,
    lobeWidth: 0.10,
    breatheAmount: 0.12,
    breathePeriod: 3.5,
    driftPeriods: [11, -17, 23],      // seconds per lap, mixed directions
    dprCap: 2,
    resolutionScale: 1,
    zIndex: 2147483000,
    stops: DEFAULT_STOPS
  };

  function compile(gl, type, src) {
    var sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      var log = gl.getShaderInfoLog(sh);
      gl.deleteShader(sh);
      throw new Error("SiriGlow shader: " + log);
    }
    return sh;
  }

  /* Critically-ish damped spring, used for enter/exit so the ramp has weight
     instead of easing linearly. */
  function Spring(value, stiffness, damping) {
    this.x = value;
    this.v = 0;
    this.target = value;
    this.k = stiffness;
    this.c = damping;
  }
  Spring.prototype.step = function (dt) {
    // Clamped so a stalled tab cannot integrate a huge dt and explode.
    dt = Math.min(dt, 1 / 30);
    var a = -this.k * (this.x - this.target) - this.c * this.v;
    this.v += a * dt;
    this.x += this.v * dt;
    return this.x;
  };

  function SiriGlow(options) {
    options = options || {};
    var o = {};
    for (var key in DEFAULTS) o[key] = DEFAULTS[key];
    for (var k2 in options) o[k2] = options[k2];
    this.opts = o;

    this.state = "idle";
    this.amplitude = 0;

    this._env = 0;
    this._phase = [0.0, 0.33, 0.66];
    this._t = 0;
    this._last = 0;
    this._raf = 0;
    this._mic = null;
    this._destroyed = false;

    this._reduce = global.matchMedia
      ? global.matchMedia("(prefers-reduced-motion: reduce)")
      : { matches: false };

    this._opacity = new Spring(0, 180, 22);
    this._scale = new Spring(0.7, 180, 22);   // drives lambda on enter/exit

    this._build();
  }

  SiriGlow.prototype._build = function () {
    var host = this.opts.target || document.body;

    var canvas = document.createElement("canvas");
    canvas.setAttribute("aria-hidden", "true");
    var s = canvas.style;
    s.position = "fixed";
    s.left = "0";
    s.top = "0";
    s.width = "100%";
    s.height = "100%";
    s.zIndex = String(this.opts.zIndex);
    // Must never intercept touch or clicks.
    s.pointerEvents = "none";
    s.mixBlendMode = "plus-lighter";
    if (s.mixBlendMode !== "plus-lighter") s.mixBlendMode = "screen";
    this.canvas = canvas;

    // Safe-area probe: env() is only readable through a real element.
    var probe = document.createElement("div");
    probe.style.cssText =
      "position:fixed;left:0;top:0;width:0;height:0;pointer-events:none;" +
      "visibility:hidden;padding:env(safe-area-inset-top) " +
      "env(safe-area-inset-right) env(safe-area-inset-bottom) " +
      "env(safe-area-inset-left);";
    this._probe = probe;

    host.appendChild(probe);
    host.appendChild(canvas);

    var attrs = { alpha: true, premultipliedAlpha: true, antialias: false,
                  depth: false, stencil: false, powerPreference: "low-power" };
    var gl = canvas.getContext("webgl", attrs) ||
             canvas.getContext("experimental-webgl", attrs);

    if (!gl) {
      // Required fallback: no WebGL, so approximate with CSS. Static, but it
      // never leaves the feature simply missing.
      this._cssFallback(host);
      return;
    }
    this.gl = gl;

    this.p3 = false;
    try {
      if ("drawingBufferColorSpace" in gl) {
        gl.drawingBufferColorSpace = "display-p3";
        this.p3 = gl.drawingBufferColorSpace === "display-p3";
      }
    } catch (e) { this.p3 = false; }

    var prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error("SiriGlow link: " + gl.getProgramInfoLog(prog));
    }
    gl.useProgram(prog);
    this.prog = prog;

    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(prog, "aPos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    this.u = {};
    var names = ["uRes", "uInset", "uRadius", "uPnorm", "uLambda", "uBloomW",
                 "uBloomS", "uOpacity", "uHairline", "uNoise", "uLobeGain",
                 "uLobeWidth", "uLobePos", "uTime", "uP3",
                 "uStop0", "uStop1", "uStop2", "uStop3"];
    for (var i = 0; i < names.length; i++) {
      this.u[names[i]] = gl.getUniformLocation(prog, names[i]);
    }

    gl.disable(gl.DEPTH_TEST);
    gl.clearColor(0, 0, 0, 0);

    this._onResize = this._resize.bind(this);
    global.addEventListener("resize", this._onResize);
    global.addEventListener("orientationchange", this._onResize);
    this._resize();

    this._last = performance.now();
    this._tick = this._frame.bind(this);
    this._raf = requestAnimationFrame(this._tick);
  };

  SiriGlow.prototype._cssFallback = function (host) {
    var el = document.createElement("div");
    el.setAttribute("aria-hidden", "true");
    el.style.cssText =
      "position:fixed;inset:0;pointer-events:none;opacity:0;" +
      "transition:opacity .35s ease;z-index:" + this.opts.zIndex + ";" +
      "border-radius:" + this.opts.radius + "px;" +
      "box-shadow:inset 0 0 90px 10px rgba(255,60,180,.45)," +
      "inset 0 0 160px 30px rgba(80,120,255,.30);";
    // corner-shape gives the superellipse; border-radius above is the fallback
    // that must ship alongside it.
    if (global.CSS && CSS.supports && CSS.supports("corner-shape", "superellipse(2)")) {
      el.style.cornerShape = "superellipse(2)";
    }
    host.appendChild(el);
    this.fallbackEl = el;
    this.canvas.remove();
    this.canvas = null;
  };

  SiriGlow.prototype._resize = function () {
    if (!this.gl) return;
    var dpr = Math.min(global.devicePixelRatio || 1, this.opts.dprCap);
    dpr *= this.opts.resolutionScale;
    var w = Math.max(1, Math.round(global.innerWidth * dpr));
    var h = Math.max(1, Math.round(global.innerHeight * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.dpr = dpr;
    this.gl.viewport(0, 0, w, h);
  };

  SiriGlow.prototype._insets = function () {
    var cs = getComputedStyle(this._probe);
    var d = this.dpr || 1;
    return [
      (parseFloat(cs.paddingTop) || 0) * d,
      (parseFloat(cs.paddingRight) || 0) * d,
      (parseFloat(cs.paddingBottom) || 0) * d,
      (parseFloat(cs.paddingLeft) || 0) * d
    ];
  };

  /* State -> the two things every state actually controls: how much light
     there is, and how fast it moves. */
  SiriGlow.prototype._targets = function () {
    switch (this.state) {
      case "enter":
      case "listening":
      case "thinking":
        return { opacity: 1, scale: 1 };
      case "exit":
        return { opacity: 0, scale: 0.82 };
      default:
        return { opacity: 0, scale: 0.7 };
    }
  };

  SiriGlow.prototype._frame = function (now) {
    if (this._destroyed) return;
    var dt = Math.min((now - this._last) / 1000, 0.1);
    this._last = now;
    this._t += dt;

    var reduce = this._reduce.matches;

    // Amplitude envelope: fast attack, slow release, so a transient shows up
    // immediately but the glow does not stutter between syllables.
    var input = this.amplitude;
    if (this.state === "thinking") {
      input = 0.45 + 0.45 * Math.sin((this._t / 1.2) * Math.PI * 2);
    } else if (this.state === "idle" || this.state === "exit") {
      input = 0;
    }
    var tau = input > this._env ? 0.040 : 0.250;
    this._env += (input - this._env) * (1 - Math.exp(-dt / tau));

    var tgt = this._targets();
    this._opacity.target = tgt.opacity;
    this._scale.target = tgt.scale;
    var op = this._opacity.step(dt);
    var sc = this._scale.step(dt);

    if (op < 0.002 && tgt.opacity === 0) {
      if (this.gl) {
        this.gl.clear(this.gl.COLOR_BUFFER_BIT);
      }
      // Fully faded and nothing asked for: sleep. This used to schedule
      // another frame here, forever, so an invisible full-screen canvas with
      // plus-lighter blending made the compositor re-blend the whole window on
      // every refresh - measured as most of the page's idle CPU. The state
      // setter below wakes the loop again when there is something to show.
      this._raf = 0;
      return;
    }

    // Drift. Reduced motion freezes the lobes but keeps the glow.
    var driftMul = 1 + 0.55 * this._env;
    if (this.state === "thinking") driftMul *= 1.4;
    if (!reduce) {
      for (var i = 0; i < 3; i++) {
        this._phase[i] += (dt / this.opts.driftPeriods[i]) * driftMul;
        this._phase[i] -= Math.floor(this._phase[i]);
      }
    }

    var breathe = reduce ? 0 :
      Math.sin((this._t / this.opts.breathePeriod) * Math.PI * 2) *
      this.opts.breatheAmount;

    var lambda = this.opts.lambda * sc * (1 + breathe) * (1 + 0.75 * this._env);
    var opacity = op * (1 + breathe * 0.5) * (0.55 + 0.45 * this._env);

    this._draw(lambda, opacity);
    this._raf = requestAnimationFrame(this._tick);
  };

  SiriGlow.prototype._draw = function (lambda, opacity) {
    var gl = this.gl, u = this.u, o = this.opts, d = this.dpr || 1;
    gl.clear(gl.COLOR_BUFFER_BIT);

    gl.uniform2f(u.uRes, this.canvas.width, this.canvas.height);
    var ins = this._insets();
    gl.uniform4f(u.uInset, ins[0], ins[1], ins[2], ins[3]);
    gl.uniform1f(u.uRadius, o.radius * d);
    gl.uniform1f(u.uPnorm, o.pnorm);
    gl.uniform1f(u.uLambda, Math.max(lambda * d, 1));
    gl.uniform3f(u.uBloomW, o.bloomWeights[0], o.bloomWeights[1], o.bloomWeights[2]);
    gl.uniform3f(u.uBloomS, o.bloomSigmas[0], o.bloomSigmas[1], o.bloomSigmas[2]);
    gl.uniform1f(u.uOpacity, Math.max(opacity, 0));
    gl.uniform1f(u.uHairline, o.hairline);
    gl.uniform1f(u.uNoise, o.noise);
    gl.uniform1f(u.uLobeGain, o.lobeGain);
    gl.uniform1f(u.uLobeWidth, o.lobeWidth);
    gl.uniform3f(u.uLobePos, this._phase[0], this._phase[1], this._phase[2]);
    gl.uniform1f(u.uTime, this._t);
    gl.uniform1f(u.uP3, this.p3 ? 1 : 0);
    for (var i = 0; i < 4; i++) {
      var st = o.stops[i];
      gl.uniform3f(u["uStop" + i], st[0], st[1], st[2]);
    }
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };

  /* Opt-in only: never called automatically, because getUserMedia must follow
     a deliberate user gesture. */
  SiriGlow.prototype.listenToMic = function () {
    var self = this;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return Promise.reject(new Error("getUserMedia unavailable"));
    }
    return navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var Ctx = global.AudioContext || global.webkitAudioContext;
      var ctx = new Ctx();
      var src = ctx.createMediaStreamSource(stream);
      var an = ctx.createAnalyser();
      an.fftSize = 1024;
      src.connect(an);
      var buf = new Float32Array(an.fftSize);
      self._mic = { ctx: ctx, stream: stream, analyser: an, buf: buf };
      (function poll() {
        if (!self._mic || self._destroyed) return;
        an.getFloatTimeDomainData(buf);
        var sum = 0;
        for (var i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
        var rms = Math.sqrt(sum / buf.length);
        self.amplitude = Math.min(1, rms * 6);
        requestAnimationFrame(poll);
      })();
      return stream;
    });
  };

  SiriGlow.prototype.stopMic = function () {
    if (!this._mic) return;
    this._mic.stream.getTracks().forEach(function (t) { t.stop(); });
    try { this._mic.ctx.close(); } catch (e) {}
    this._mic = null;
    this.amplitude = 0;
  };

  /* Restart the render loop if it went to sleep. The clock is re-seeded so the
     first frame after a long idle does not see a huge dt and jump. */
  SiriGlow.prototype._wake = function () {
    if (this._raf || this._destroyed || !this.gl || !this._tick) return;
    this._last = performance.now();
    this._raf = requestAnimationFrame(this._tick);
  };

  SiriGlow.prototype.set = function (key, value) {
    this.opts[key] = value;
    if (this.fallbackEl && key === "radius") {
      this.fallbackEl.style.borderRadius = value + "px";
    }
  };

  SiriGlow.prototype.destroy = function () {
    this._destroyed = true;
    if (this._raf) cancelAnimationFrame(this._raf);
    this.stopMic();
    if (this._onResize) {
      global.removeEventListener("resize", this._onResize);
      global.removeEventListener("orientationchange", this._onResize);
    }
    if (this.canvas) this.canvas.remove();
    if (this.fallbackEl) this.fallbackEl.remove();
    if (this._probe) this._probe.remove();
  };

  // The CSS fallback has no render loop, so mirror state onto opacity.
  var _origSetState = Object.getOwnPropertyDescriptor(SiriGlow.prototype, "state");
  if (!_origSetState) {
    Object.defineProperty(SiriGlow.prototype, "state", {
      get: function () { return this._state || "idle"; },
      set: function (v) {
        this._state = v;
        if (this.fallbackEl) {
          this.fallbackEl.style.opacity =
            (v === "idle" || v === "exit") ? "0" : "1";
        }
        this._wake();
      }
    });
  }

  global.SiriGlow = SiriGlow;
})(typeof window !== "undefined" ? window : this);
