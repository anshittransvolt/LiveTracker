(function(){
    // Dynamically load CSS
    function loadCSS(href){
        var l = document.createElement('link');
        l.rel = 'stylesheet'; l.href = href; l.type = 'text/css';
        document.getElementsByTagName('head')[0].appendChild(l);
    }
    function loadScript(src, cb){
        var s = document.createElement('script');
        s.src = src; s.async = false;
        s.onload = function(){ if(cb) cb(); };
        document.getElementsByTagName('head')[0].appendChild(s);
    }

    // Load toastr CSS + jQuery and toastr JS
    loadCSS('https://cdnjs.cloudflare.com/ajax/libs/toastr.js/latest/toastr.min.css');
    // Load jQuery only if not present
    function ensureJquery(next){
        if (window.jQuery) return next();
        loadScript('https://code.jquery.com/jquery-3.6.0.min.js', next);
    }

    ensureJquery(function(){
        // load toastr
        loadScript('https://cdnjs.cloudflare.com/ajax/libs/toastr.js/latest/toastr.min.js', function(){
            try {
                // configure toastr
                if (window.toastr) {
                    toastr.options = {
                        closeButton: true,
                        debug: false,
                        newestOnTop: true,
                        progressBar: true,
                        positionClass: 'toast-top-right',
                        preventDuplicates: true,
                        timeOut: '5000'
                    };
                }

                // Find Django admin messages and convert to toasts
                // Django admin messages typically are inside <ul class="messagelist"><li class="...">Message</li>...</ul>
                var lists = document.querySelectorAll('.messagelist li');
                lists.forEach(function(li){
                    var cls = li.className || '';
                    var text = li.innerText || li.textContent || '';
                    text = text.trim();
                    if (!text) return;
                    if (cls.indexOf('error') !== -1) {
                        toastr.error(text);
                    } else if (cls.indexOf('warning') !== -1) {
                        toastr.warning(text);
                    } else if (cls.indexOf('success') !== -1) {
                        toastr.success(text);
                    } else {
                        toastr.info(text);
                    }
                });
            } catch (e){
                console.warn('admin_toastr init error', e);
            }
        });
    });
})();
