/**
 * Просмотр рисунка turtle: масштаб, прокрутка, оверлей на весь экран, Ctrl+колёсико = zoom.
 * Инициализация: BooTurtleImageViewer.initAll() на DOMContentLoaded; после смены src: BooTurtleImageViewer.refresh(wrap).
 */
(function (global) {
    'use strict';

    var MIN = 0.1;
    var MAX = 8;
    var ZOOM_MULT = 1.15;
    var LB_ID = 'boo-turtle-lightbox';

    function clamp(n, a, b) {
        return Math.max(a, Math.min(b, n));
    }

    /** Масштаб «вписать в прямоугольник» (от натурального размера), не шире 1:1. */
    function getFitScaleInBox(img, boxW, boxH, pad) {
        if (!img.naturalWidth || !img.naturalHeight) return 1;
        if (boxW < 4) boxW = 400;
        if (boxH < 4) boxH = 300;
        var sx = (boxW - pad * 2) / img.naturalWidth;
        var sy = (boxH - pad * 2) / img.naturalHeight;
        return clamp(Math.min(sx, sy), MIN, 1);
    }

    function getInlineFitScale(img, viewport) {
        if (!img.naturalWidth || !viewport) return 1;
        var w = viewport.clientWidth;
        if (w < 4) w = 300;
        var maxH = 400;
        var cs = global.getComputedStyle(viewport);
        if (cs && cs.maxHeight) {
            var m = parseFloat(cs.maxHeight);
            if (m > 0 && m < 2000) maxH = m;
        }
        var h = Math.min(maxH, viewport.clientHeight || maxH) || maxH;
        if (h < 40) h = 200;
        return getFitScaleInBox(img, w, h, 8);
    }

    function applySize(img, scale) {
        if (!img.naturalWidth) return;
        var w = Math.max(1, Math.round(img.naturalWidth * scale));
        var h = Math.max(1, Math.round(img.naturalHeight * scale));
        img.style.width = w + 'px';
        img.style.height = h + 'px';
        img.style.maxWidth = 'none';
        img.style.maxHeight = 'none';
    }

    function setLabel(root, elClass, scale) {
        var el = root.querySelector('.' + elClass);
        if (el) el.textContent = Math.round(scale * 100) + '%';
    }

    function getInlineState(wrap) {
        if (!wrap._booTurtle) {
            wrap._booTurtle = { scale: 1, fit: 1 };
        }
        return wrap._booTurtle;
    }

    function onInlineImageReady(wrap) {
        var img = wrap.querySelector('.code-editor-turtle-img');
        var vp = wrap.querySelector('.code-editor-turtle-viewport');
        if (!img || !vp) return;
        if (!img.naturalWidth) return;
        var st = getInlineState(wrap);
        st.fit = getInlineFitScale(img, vp);
        st.scale = st.fit;
        applySize(img, st.scale);
        setLabel(wrap, 'code-editor-turtle-zoom-pct', st.scale);
        vp.scrollLeft = 0;
        vp.scrollTop = 0;
    }

    function zoomInline(wrap, dir) {
        var img = wrap.querySelector('.code-editor-turtle-img');
        if (!img || !img.naturalWidth) return;
        var st = getInlineState(wrap);
        var f = dir > 0 ? ZOOM_MULT : 1 / ZOOM_MULT;
        st.scale = clamp(st.scale * f, MIN, MAX);
        applySize(img, st.scale);
        setLabel(wrap, 'code-editor-turtle-zoom-pct', st.scale);
    }

    function resetInlineFit(wrap) {
        onInlineImageReady(wrap);
    }

    function oneToOneInline(wrap) {
        var img = wrap.querySelector('.code-editor-turtle-img');
        var vp = wrap.querySelector('.code-editor-turtle-viewport');
        if (!img || !img.naturalWidth) return;
        var st = getInlineState(wrap);
        st.scale = 1;
        applySize(img, 1);
        setLabel(wrap, 'code-editor-turtle-zoom-pct', 1);
        if (vp) {
            vp.scrollLeft = 0;
            vp.scrollTop = 0;
        }
    }

    var _lbLayoutAttempts = 0;

    function getOrCreateLightbox() {
        var ex = document.getElementById(LB_ID);
        if (ex) return ex;

        var root = document.createElement('div');
        root.id = LB_ID;
        root.className = 'boo-turtle-lightbox';
        root.setAttribute('hidden', 'hidden');
        root.setAttribute('role', 'presentation');
        root.innerHTML =
            '<div class="boo-turtle-lb-backdrop" data-boo-turtle-close="1" aria-hidden="true"></div>' +
            '<div class="boo-turtle-lb-panel" role="dialog" aria-modal="true" aria-label="Просмотр рисунка turtle">' +
            '<div class="boo-turtle-lb-header">' +
            '<span class="boo-turtle-lb-title">Рисунок turtle</span>' +
            '<div class="boo-turtle-lb-toolbar" role="toolbar" aria-label="Масштаб">' +
            '<button type="button" class="code-editor-turtle-btn neo-button ghost sm" data-turtle-lb="zoom-out" title="Уменьшить" aria-label="Уменьшить"><i class="ph-bold ph-minus" aria-hidden="true"></i></button>' +
            '<span class="boo-turtle-lb-zoom-pct" aria-live="polite">100%</span>' +
            '<button type="button" class="code-editor-turtle-btn neo-button ghost sm" data-turtle-lb="zoom-in" title="Увеличить" aria-label="Увеличить"><i class="ph-bold ph-plus" aria-hidden="true"></i></button>' +
            '<button type="button" class="code-editor-turtle-btn neo-button ghost sm" data-turtle-lb="fit" title="Вписать в окно" aria-label="Вписать в окно"><i class="ph-bold ph-arrows-in-simple" aria-hidden="true"></i></button>' +
            '<button type="button" class="code-editor-turtle-btn neo-button ghost sm" data-turtle-lb="one" title="1:1 натуральный размер" aria-label="Натуральный размер 1 к 1">1:1</button>' +
            '<button type="button" class="code-editor-turtle-btn neo-button ghost sm" data-turtle-lb="fs" title="Полноэкранный режим браузера" aria-label="Полноэкранный режим"><i class="ph-bold ph-arrows-out" aria-hidden="true"></i></button>' +
            '<button type="button" class="code-editor-turtle-btn neo-button ghost sm" data-turtle-lb="close" title="Закрыть" aria-label="Закрыть">Esc</button>' +
            '</div></div>' +
            '<div class="boo-turtle-lb-viewport" tabindex="0" aria-label="Прокрутка: панорама. Ctrl+колёсико: масштаб.">' +
            '<div class="boo-turtle-lb-canvas"><img class="boo-turtle-lb-img" alt="Рисунок turtle" /></div>' +
            '</div>' +
            '<p class="boo-turtle-lb-hint">Прокрутка — панорама. <kbd>Ctrl</kbd>+колёсико — масштаб. <kbd>Esc</kbd> — выход.</p>' +
            '</div>';
        document.body.appendChild(root);
        return root;
    }

    function getLbState() {
        var root = getOrCreateLightbox();
        if (!root._booTurtle) {
            root._booTurtle = { scale: 1, fit: 1 };
        }
        return root._booTurtle;
    }

    function onLbImageReady() {
        var root = getOrCreateLightbox();
        var img = root.querySelector('.boo-turtle-lb-img');
        var vp = root.querySelector('.boo-turtle-lb-viewport');
        if (!img || !img.naturalWidth || !vp) return;
        var vw = vp.clientWidth;
        var vh = vp.clientHeight;
        if (vw < 4 || vh < 4) {
            if (_lbLayoutAttempts < 20) {
                _lbLayoutAttempts += 1;
                requestAnimationFrame(function () {
                    onLbImageReady();
                });
            } else {
                _lbLayoutAttempts = 0;
            }
            return;
        }
        _lbLayoutAttempts = 0;
        var st = getLbState();
        st.fit = getFitScaleInBox(img, vw, vh, 8);
        st.scale = st.fit;
        applySize(img, st.scale);
        setLabel(root, 'boo-turtle-lb-zoom-pct', st.scale);
        vp.scrollLeft = 0;
        vp.scrollTop = 0;
        try {
            vp.focus({ preventScroll: true });
        } catch (e) {
            vp.focus();
        }
    }

    function zoomLb(dir) {
        var root = getOrCreateLightbox();
        var img = root.querySelector('.boo-turtle-lb-img');
        if (!img || !img.naturalWidth) return;
        var st = getLbState();
        var f = dir > 0 ? ZOOM_MULT : 1 / ZOOM_MULT;
        st.scale = clamp(st.scale * f, MIN, MAX);
        applySize(img, st.scale);
        setLabel(root, 'boo-turtle-lb-zoom-pct', st.scale);
    }

    function resetLbFit() {
        onLbImageReady();
    }

    function oneToOneLb() {
        var root = getOrCreateLightbox();
        var img = root.querySelector('.boo-turtle-lb-img');
        var vp = root.querySelector('.boo-turtle-lb-viewport');
        if (!img || !img.naturalWidth) return;
        var st = getLbState();
        st.scale = 1;
        applySize(img, 1);
        setLabel(root, 'boo-turtle-lb-zoom-pct', 1);
        if (vp) {
            vp.scrollLeft = 0;
            vp.scrollTop = 0;
        }
    }

    function closeLightbox() {
        var root = document.getElementById(LB_ID);
        if (!root) return;
        if (document.fullscreenElement && document.exitFullscreen) {
            document.exitFullscreen().catch(function () {});
        }
        root.setAttribute('hidden', 'hidden');
        document.body.style.overflow = '';
    }

    function openLightboxFromSourceImg(sourceImg) {
        if (!sourceImg || !sourceImg.getAttribute('src')) return;
        _lbLayoutAttempts = 0;
        var root = getOrCreateLightbox();
        var lbImg = root.querySelector('.boo-turtle-lb-img');
        lbImg.src = sourceImg.currentSrc || sourceImg.src;
        root.removeAttribute('hidden');
        document.body.style.overflow = 'hidden';
        function afterSrcReady() {
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    onLbImageReady();
                });
            });
        }
        if (lbImg.complete && lbImg.naturalWidth) {
            afterSrcReady();
        } else {
            lbImg.onload = function () {
                lbImg.onload = null;
                afterSrcReady();
            };
        }
    }

    function tryBrowserFullscreen() {
        var root = getOrCreateLightbox();
        var panel = root.querySelector('.boo-turtle-lb-panel');
        if (!panel) return;
        if (document.fullscreenElement) {
            if (document.exitFullscreen) document.exitFullscreen();
            return;
        }
        if (panel.requestFullscreen) {
            panel.requestFullscreen().then(function () {
                _lbLayoutAttempts = 0;
                onLbImageReady();
            }).catch(function () {});
        }
    }

    var escBound = false;
    function ensureLightboxKeyHandlers() {
        if (escBound) return;
        escBound = true;
        document.addEventListener(
            'keydown',
            function (e) {
                if (e.key !== 'Escape') return;
                var root = document.getElementById(LB_ID);
                if (root && !root.hasAttribute('hidden')) {
                    e.preventDefault();
                    closeLightbox();
                }
            },
            true
        );
    }

    var lbFsResizeT;
    function onLightboxLayoutMaybeChanged() {
        var r = document.getElementById(LB_ID);
        if (!r || r.hasAttribute('hidden')) return;
        clearTimeout(lbFsResizeT);
        lbFsResizeT = setTimeout(function () {
            onLbImageReady();
        }, 50);
    }

    function bindLightbox() {
        var root = getOrCreateLightbox();
        if (root._booTurtleInit) return;
        root._booTurtleInit = true;
        document.addEventListener('fullscreenchange', function () {
            if (!document.getElementById(LB_ID)) return;
            onLightboxLayoutMaybeChanged();
        });
        ensureLightboxKeyHandlers();
        root.addEventListener('click', function (e) {
            if (e.target.getAttribute('data-boo-turtle-close')) {
                e.preventDefault();
                closeLightbox();
            }
        });
        root.querySelector('.boo-turtle-lb-panel').addEventListener('click', function (e) {
            var b = e.target.closest('[data-turtle-lb]');
            if (!b) return;
            var act = b.getAttribute('data-turtle-lb');
            e.preventDefault();
            if (act === 'zoom-in') zoomLb(1);
            else if (act === 'zoom-out') zoomLb(-1);
            else if (act === 'fit') resetLbFit();
            else if (act === 'one') oneToOneLb();
            else if (act === 'fs') tryBrowserFullscreen();
            else if (act === 'close') closeLightbox();
        });
        var lbVp = root.querySelector('.boo-turtle-lb-viewport');
        if (lbVp) {
            lbVp.addEventListener(
                'wheel',
                function (e) {
                    if (e.ctrlKey) {
                        e.preventDefault();
                        zoomLb(e.deltaY < 0 ? 1 : -1);
                    }
                },
                { passive: false }
            );
        }
        var lbPanelImg = root.querySelector('.boo-turtle-lb-img');
        if (lbPanelImg) {
            lbPanelImg.addEventListener('dblclick', function (e) {
                e.preventDefault();
                resetLbFit();
            });
        }
    }

    function initWrap(wrap) {
        if (!wrap || wrap.getAttribute('data-boo-turtle-inited') === '1') return;
        wrap.setAttribute('data-boo-turtle-inited', '1');
        var vp = wrap.querySelector('.code-editor-turtle-viewport');
        var img = wrap.querySelector('.code-editor-turtle-img');
        var bar = wrap.querySelector('.code-editor-turtle-toolbar');
        if (vp) {
            vp.addEventListener(
                'wheel',
                function (e) {
                    if (e.ctrlKey) {
                        e.preventDefault();
                        zoomInline(wrap, e.deltaY < 0 ? 1 : -1);
                    }
                },
                { passive: false }
            );
        }
        if (img) {
            img.addEventListener('dblclick', function (e) {
                e.preventDefault();
                resetInlineFit(wrap);
            });
        }
        if (bar) {
            bar.addEventListener('click', function (e) {
                var b = e.target.closest('[data-turtle]');
                if (!b) return;
                var act = b.getAttribute('data-turtle');
                e.preventDefault();
                if (act === 'zoom-in') zoomInline(wrap, 1);
                else if (act === 'zoom-out') zoomInline(wrap, -1);
                else if (act === 'fit') resetInlineFit(wrap);
                else if (act === 'one') oneToOneInline(wrap);
                else if (act === 'expand') {
                    var im = wrap.querySelector('.code-editor-turtle-img');
                    if (im) {
                        bindLightbox();
                        openLightboxFromSourceImg(im);
                    }
                }
            });
        }
        if (img && img.getAttribute('src') && img.complete) {
            onInlineImageReady(wrap);
        } else if (img) {
            img.addEventListener('load', function onI() {
                img.removeEventListener('load', onI);
                onInlineImageReady(wrap);
            });
        }
    }

    function initAll() {
        document.querySelectorAll('.code-editor-turtle-wrap').forEach(initWrap);
        bindLightbox();
    }

    function refresh(wrap) {
        if (!wrap) return;
        var img = wrap.querySelector('.code-editor-turtle-img');
        function doReady() {
            onInlineImageReady(wrap);
        }
        if (img && img.complete && img.naturalWidth) {
            setTimeout(doReady, 0);
        } else if (img) {
            img.addEventListener('load', function h() {
                img.removeEventListener('load', h);
                setTimeout(doReady, 0);
            });
        }
    }

    global.BooTurtleImageViewer = {
        initAll: initAll,
        refresh: refresh,
    };
})(typeof window !== 'undefined' ? window : this);
