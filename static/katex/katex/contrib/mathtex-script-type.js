(function webpackUniversalModuleDefinition(root, factory) {
	if(typeof exports === 'object' && typeof module === 'object')
		module.exports = factory(require("katex"));
	else if(typeof define === 'function' && define.amd)
		define(["katex"], factory);
	else {
		var a = typeof exports === 'object' ? factory(require("katex")) : factory(root["katex"]);
		for(var i in a) (typeof exports === 'object' ? exports : root)[i] = a[i];
	}
})((typeof self !== 'undefined' ? self : this), function(__WEBPACK_EXTERNAL_MODULE__771__) {
return  (function() { 
 	"use strict";
 	var __webpack_modules__ = ({

 771:
 (function(module) {

module.exports = __WEBPACK_EXTERNAL_MODULE__771__;

 })

 	});

 	var __webpack_module_cache__ = {};

 	function __webpack_require__(moduleId) {
 		
 		var cachedModule = __webpack_module_cache__[moduleId];
 		if (cachedModule !== undefined) {
 			return cachedModule.exports;
 		}
 		
 		var module = __webpack_module_cache__[moduleId] = {

 			exports: {}
 		};

 		__webpack_modules__[moduleId](module, module.exports, __webpack_require__);

 		return module.exports;
 	}

 	!function() {
 		
 		__webpack_require__.n = function(module) {
 			var getter = module && module.__esModule ?
 				function() { return module['default']; } :
 				function() { return module; };
 			__webpack_require__.d(getter, { a: getter });
 			return getter;
 		};
 	}();

 	!function() {
 		
 		__webpack_require__.d = function(exports, definition) {
 			for(var key in definition) {
 				if(__webpack_require__.o(definition, key) && !__webpack_require__.o(exports, key)) {
 					Object.defineProperty(exports, key, { enumerable: true, get: definition[key] });
 				}
 			}
 		};
 	}();

 	!function() {
 		__webpack_require__.o = function(obj, prop) { return Object.prototype.hasOwnProperty.call(obj, prop); }
 	}();

var __webpack_exports__ = {};

!function() {
 var katex__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(771);
 var katex__WEBPACK_IMPORTED_MODULE_0___default = __webpack_require__.n(katex__WEBPACK_IMPORTED_MODULE_0__);

var scripts = document.body.getElementsByTagName("script");
scripts = Array.prototype.slice.call(scripts);
scripts.forEach(function (script) {
  if (!script.type || !script.type.match(/math\/tex/i)) {
    return -1;
  }

  var display = script.type.match(/mode\s*=\s*display(;|\s|\n|$)/) != null;
  var katexElement = document.createElement(display ? "div" : "span");
  katexElement.setAttribute("class", display ? "equation" : "inline-equation");

  try {
    katex__WEBPACK_IMPORTED_MODULE_0___default().render(script.text, katexElement, {
      displayMode: display
    });
  } catch (err) {
    
    katexElement.textContent = script.text;
  }

  script.parentNode.replaceChild(katexElement, script);
});
}();
__webpack_exports__ = __webpack_exports__["default"];
 	return __webpack_exports__;
 })()
;
});