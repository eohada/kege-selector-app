(function webpackUniversalModuleDefinition(root, factory) {
	if(typeof exports === 'object' && typeof module === 'object')
		module.exports = factory();
	else if(typeof define === 'function' && define.amd)
		define([], factory);
	else {
		var a = factory();
		for(var i in a) (typeof exports === 'object' ? exports : root)[i] = a[i];
	}
})((typeof self !== 'undefined' ? self : this), function() {
return  (function() { 
 	"use strict";
var __webpack_exports__ = {};

;

var defaultCopyDelimiters = {
  inline: ['$', '$'],
  
  display: ['$$', '$$'] 

}; 

function katexReplaceWithTex(fragment, copyDelimiters) {
  if (copyDelimiters === void 0) {
    copyDelimiters = defaultCopyDelimiters;
  }

  var katexHtml = fragment.querySelectorAll('.katex-mathml + .katex-html');

  for (var i = 0; i < katexHtml.length; i++) {
    var element = katexHtml[i];

    if (element.remove) {
      element.remove();
    } else if (element.parentNode) {
      element.parentNode.removeChild(element);
    }
  } 

  var katexMathml = fragment.querySelectorAll('.katex-mathml');

  for (var _i = 0; _i < katexMathml.length; _i++) {
    var _element = katexMathml[_i];

    var texSource = _element.querySelector('annotation');

    if (texSource) {
      if (_element.replaceWith) {
        _element.replaceWith(texSource);
      } else if (_element.parentNode) {
        _element.parentNode.replaceChild(texSource, _element);
      }

      texSource.innerHTML = copyDelimiters.inline[0] + texSource.innerHTML + copyDelimiters.inline[1];
    }
  } 

  var displays = fragment.querySelectorAll('.katex-display annotation');

  for (var _i2 = 0; _i2 < displays.length; _i2++) {
    var _element2 = displays[_i2];
    _element2.innerHTML = copyDelimiters.display[0] + _element2.innerHTML.substr(copyDelimiters.inline[0].length, _element2.innerHTML.length - copyDelimiters.inline[0].length - copyDelimiters.inline[1].length) + copyDelimiters.display[1];
  }

  return fragment;
}
 var katex2tex = (katexReplaceWithTex);
;

function closestKatex(node) {

  var element = node instanceof Element ? node : node.parentElement;
  return element && element.closest('.katex');
} 

document.addEventListener('copy', function (event) {
  var selection = window.getSelection();

  if (selection.isCollapsed || !event.clipboardData) {
    return; 
  }

  var clipboardData = event.clipboardData;
  var range = selection.getRangeAt(0); 

  var startKatex = closestKatex(range.startContainer);

  if (startKatex) {
    range.setStartBefore(startKatex);
  } 

  var endKatex = closestKatex(range.endContainer);

  if (endKatex) {
    range.setEndAfter(endKatex);
  }

  var fragment = range.cloneContents();

  if (!fragment.querySelector('.katex-mathml')) {
    return; 
  }

  var htmlContents = Array.prototype.map.call(fragment.childNodes, function (el) {
    return el instanceof Text ? el.textContent : el.outerHTML;
  }).join(''); 

  clipboardData.setData('text/html', htmlContents); 

  clipboardData.setData('text/plain', katex2tex(fragment).textContent); 

  event.preventDefault();
});
__webpack_exports__ = __webpack_exports__["default"];
 	return __webpack_exports__;
 })()
;
});