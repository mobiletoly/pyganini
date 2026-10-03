/* Application-owned full-page refresh for the explicit development host. */
(function () {
    "use strict";
    const script = document.currentScript;
    const url = script && script.dataset.eventsUrl;
    if (!url) return;
    const source = new EventSource(url);
    let previous = null;
    source.addEventListener("reload", function (event) {
        const revision = event.data;
        if (previous === null) {
            previous = revision;
        } else if (revision !== previous) {
            previous = revision;
            source.close();
            location.reload();
        }
    });
    window.addEventListener("pagehide", function () { source.close(); }, {once: true});
}());
