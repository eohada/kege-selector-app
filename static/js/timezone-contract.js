/**
 * BooStudy Unified Timezone Contract (static/js/timezone-contract.js)
 * 
 * Rules:
 * 1. The viewer's profile IANA timezone (from <meta name="user-timezone-effective">)
 *    is the single source of truth for display.
 * 2. All server events and deadlines are delivered as UTC instants (ISO with 'Z').
 * 3. Form input: local date + local time + profile IANA timezone -> converted to UTC ISO once.
 * 4. Display: formatted in viewer's timezone using Intl.DateTimeFormat with explicit timeZone.
 */
(function(window) {
  'use strict';

  function getViewerTz() {
    const meta = document.querySelector('meta[name="user-timezone-effective"]');
    const val = meta ? meta.getAttribute('content') : null;
    return (val && val.trim()) ? val.trim() : 'Europe/Moscow';
  }

  function setViewerTz(tzName) {
    if (!tzName) return;
    const meta = document.querySelector('meta[name="user-timezone-effective"]');
    if (meta) {
      meta.setAttribute('content', tzName.trim());
    }
    // Dispatch event so all listening widgets update in real time
    window.dispatchEvent(new CustomEvent('boostudy:timezone-changed', {
      detail: { timezone: tzName.trim() }
    }));
  }

  function pad2(n) {
    return String(n).padStart(2, '0');
  }

  /**
   * Convert local date ("YYYY-MM-DD" or "DD.MM.YYYY") and time ("HH:MM")
   * in specified IANA timezone into strict UTC ISO-8601 string (with 'Z').
   */
  function localToUtcIso(dateStr, timeStr, timeZone) {
    if (!dateStr) return null;
    const tz = (timeZone && timeZone.trim()) ? timeZone.trim() : getViewerTz();
    
    let year = 2026, month = 1, day = 1;
    const cleanDate = dateStr.trim();
    if (cleanDate.includes('.')) {
      const parts = cleanDate.split('.').map(Number);
      day = parts[0];
      month = parts[1];
      year = parts[2];
    } else {
      const parts = cleanDate.split('-').map(Number);
      year = parts[0];
      month = parts[1];
      day = parts[2];
    }

    let hour = 12, minute = 0;
    if (timeStr) {
      const tParts = timeStr.trim().split(':').map(Number);
      hour = isNaN(tParts[0]) ? 12 : tParts[0];
      minute = isNaN(tParts[1]) ? 0 : tParts[1];
    }

    // Converge exact UTC instant using Intl.DateTimeFormat
    let utcMs = Date.UTC(year, month - 1, day, hour, minute, 0);
    for (let iter = 0; iter < 4; iter++) {
      const probeDate = new Date(utcMs);
      const formatter = new Intl.DateTimeFormat('en-US', {
        timeZone: tz,
        year: 'numeric', month: 'numeric', day: 'numeric',
        hour: 'numeric', minute: 'numeric', second: 'numeric',
        hour12: false
      });
      const parts = Object.fromEntries(formatter.formatToParts(probeDate).map(p => [p.type, p.value]));
      let probeHour = parseInt(parts.hour, 10);
      if (probeHour === 24) probeHour = 0;
      const targetLocalMs = Date.UTC(
        parseInt(parts.year, 10),
        parseInt(parts.month, 10) - 1,
        parseInt(parts.day, 10),
        probeHour,
        parseInt(parts.minute, 10),
        parseInt(parts.second, 10)
      );
      const desiredLocalMs = Date.UTC(year, month - 1, day, hour, minute, 0);
      const diff = targetLocalMs - desiredLocalMs;
      if (diff === 0) break;
      utcMs -= diff;
    }

    return new Date(utcMs).toISOString().replace(/\.\d{3}Z$/, 'Z');
  }

  /**
   * Extract date/time parts of a UTC instant in specified IANA timezone.
   */
  function getPartsInTz(isoZ, timeZone) {
    if (!isoZ) return null;
    const tz = (timeZone && timeZone.trim()) ? timeZone.trim() : getViewerTz();
    
    // Ensure string is parsed as UTC
    let d;
    if (isoZ instanceof Date) {
      d = isoZ;
    } else {
      let str = String(isoZ).trim();
      if (!str.endsWith('Z') && !str.includes('+') && !str.includes('-')) {
        str += 'Z';
      }
      d = new Date(str);
    }

    if (isNaN(d.getTime())) return null;

    try {
      const formatter = new Intl.DateTimeFormat('en-CA', {
        timeZone: tz,
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false
      });
      const parts = Object.fromEntries(formatter.formatToParts(d).map(p => [p.type, p.value]));
      let h = parseInt(parts.hour, 10);
      if (h === 24) h = 0;
      const min = parseInt(parts.minute, 10);
      const dateStr = `${parts.year}-${parts.month}-${parts.day}`;
      const timeStr = `${pad2(h)}:${pad2(min)}`;
      return {
        year: parseInt(parts.year, 10),
        month: parseInt(parts.month, 10),
        day: parseInt(parts.day, 10),
        hour: h,
        minute: min,
        dateStr: dateStr,
        timeStr: timeStr,
        date: dateStr,
        time: timeStr,
        grid_top: h * 60 + min,
        isoZ: d.toISOString()
      };
    } catch (e) {
      // Fallback
      return {
        year: d.getUTCFullYear(),
        month: d.getUTCMonth() + 1,
        day: d.getUTCDate(),
        hour: d.getUTCHours(),
        minute: d.getUTCMinutes(),
        dateStr: d.toISOString().substring(0, 10),
        timeStr: `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`,
        grid_top: d.getUTCHours() * 60 + d.getUTCMinutes(),
        isoZ: d.toISOString()
      };
    }
  }

  /**
   * Format UTC instant in viewer's IANA timezone.
   */
  function formatUtcInTz(isoZ, timeZone, options) {
    if (!isoZ) return '—';
    const tz = (timeZone && timeZone.trim()) ? timeZone.trim() : getViewerTz();
    let d = (isoZ instanceof Date) ? isoZ : new Date(isoZ);
    if (isNaN(d.getTime())) return '—';

    const defaultOptions = {
      timeZone: tz,
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    };
    const opts = Object.assign({}, defaultOptions, options || {});
    return new Intl.DateTimeFormat('ru-RU', opts).format(d);
  }

  /**
   * Countdown text to UTC instant.
   */
  function formatCountdown(isoZ) {
    if (!isoZ) return '';
    const d = (isoZ instanceof Date) ? isoZ : new Date(isoZ);
    if (isNaN(d.getTime())) return '';
    const now = Date.now();
    const diffMs = d.getTime() - now;

    if (diffMs <= 0) {
      return 'Дедлайн прошёл';
    }
    const totalMin = Math.floor(diffMs / 60000);
    const days = Math.floor(totalMin / (24 * 60));
    const hours = Math.floor((totalMin % (24 * 60)) / 60);
    const mins = totalMin % 60;

    if (days > 0) {
      return `${days} д. ${hours} ч.`;
    }
    if (hours > 0) {
      return `${hours} ч. ${mins} мин.`;
    }
    return `${mins} мин.`;
  }

  window.BooTimezone = {
    getViewerTz: getViewerTz,
    setViewerTz: setViewerTz,
    localToUtcIso: localToUtcIso,
    getPartsInTz: getPartsInTz,
    formatUtcInTz: formatUtcInTz,
    formatCountdown: formatCountdown,
  };
})(window);
