function handleWheel(e) {
    const scrollable = e.target.closest('.overflow-y-auto');
    if (!scrollable) {
        e.preventDefault();
        return;
    }
    const atTop = scrollable.scrollTop <= 0;
    const atBottom = Math.ceil(scrollable.scrollTop + scrollable.clientHeight) >= scrollable.scrollHeight;
    if (e.deltaY < 0 && atTop) e.preventDefault();
    if (e.deltaY > 0 && atBottom) e.preventDefault();
}
