// post_preview
// previewTimer must live outside the functions.
var previewTimer = null;

function previewAjax(textarea, div, show_raw = false, mathjax = false){
    // set div to raw textarea while waiting for remote Markdown rendering.
    if (show_raw) {
	// bust HTML tags like <script> to prevent running evil code.
        var busted_textarea = $('#'+textarea).val().replace(/&/g, '&amp;').replace(/</g,'&lt;');
        // $('#' + div).html('<div class="preview-raw-markdown">'+busted_textarea+'</div>');
        $('#' + div).html('<span class="preview-raw-markdown">'+busted_textarea+'</span>');
    }
    if (previewTimer) {
        clearTimeout(previewTimer);
    }
    previewTimer = setTimeout(
        function() { sendPreview( textarea, div, mathjax ); },
	800
    );
}

function sendPreview(textarea, div, mathjax=false){
    $.ajaxSetup ({
        cache: false
    });

    var url    = '/preview-post';
    var params = { 'data' : $('#'+textarea).val(), 'csrf_token' : csrf_token };

    $( '#' + div ).load( url, params );

    if (mathjax) {
        setTimeout(function(){
            // hack: block MathJax rerender for 50ms, give div chance to load.
            MathJax.Hub.Queue(["Typeset",MathJax.Hub,div]);
        }, 100);
    }
}

// this toggles a dropdown.
function toggle(target, button, off_text, on_text="hide"){
    if (!$('#' + target + ":visible").height()){
        $('#' + target).slideDown("slow");
        $('#' + button).text(on_text);
    }
    else {
        $('#' + target).slideUp("slow");
        $('#' + button).text(off_text);
    }
}

$(document).ready( function() {

  $('button.vote-up').click(
    function(){
      var post_id = $(this).closest('div').attr('id');
      sendVote( post_id, 'up' );
    }
  );

  $('button.vote-down').click(
    function(){
      var post_id = $(this).closest('div').attr('id');
      sendVote( post_id, 'down' );
    }
  );

  // make all elements with class alert fade into existance.
  $('.alert').delay(100).animate({"opacity": "1"}, 2000);

  // highlight a fragment hash div if it exsits.
  if(window.location.hash) {
    // Fragment exists, so target the node's div.
    var fragment = '#node-data-' + window.location.hash.replace('#', '');
    $(fragment).addClass("focused");
  }

});

function sendVote( post_id, direction ){
  var url    = '/vote-post';
  var params = { 'post_id' : post_id, 'direction' : direction, 'csrf_token' : csrf_token };

  $.getJSON( url, params, function( r ){
      if ( r['status'] ) {
        $('#'+post_id).children('b').html(r['vote_sum']);
      }
      else {
        $('#json').html(r['msg']);
      }
    }
  );
}
