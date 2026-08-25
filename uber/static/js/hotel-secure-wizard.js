// Secure-room wizard state machine (hotel_lottery/secure_room.html).
//
// The template provides its per-assignment values via a small config
// stanza BEFORE this script loads:
//
//   window.secureWizardConfig = {
//     assignmentId: ...,   // RoomAssignment id posted to every endpoint
//     cardToken: ...,      // seeded card state, '' when no card on file
//     cardLastFour: ...,
//     cardType: ...,
//     redirectUrl: ...     // where to send the user after securing
//   };
//
// goToStep() and submitWithExistingCard() are referenced by inline
// onclick= handlers in the template, so they stay top-level (global).
// Relies on the app-wide globals jQuery ($) and csrf_token.

var secureWizardConfig = window.secureWizardConfig || {};

var iframeUrl = null;       // Set lazily via AJAX
var vaultSessionLoading = false;
var vaultSessionReady = false;

// Card state - seeded from server if a card was already captured on this assignment.
var cardToken = secureWizardConfig.cardToken || null;
var cardLastFour = secureWizardConfig.cardLastFour || '';
var cardType = secureWizardConfig.cardType || '';
var vaultOrigin = null;  // Set when vault iframe URL is loaded

function loadVaultSession(callback) {
  if (iframeUrl) {
    if (callback) callback();
    return;
  }
  if (vaultSessionLoading) return;
  vaultSessionLoading = true;

  $('#vault-loading').show();
  $('#vault-iframe-container').hide();
  $('#secure-error').hide();

  $.ajax({
    url: 'create_vault_session',
    method: 'POST',
    data: { assignment_id: secureWizardConfig.assignmentId, csrf_token: csrf_token },
    success: function(json) {
      vaultSessionLoading = false;
      $('#vault-loading').hide();
      if (json.success) {
        iframeUrl = json.iframe_url;
        try { vaultOrigin = new URL(iframeUrl).origin; } catch(e) {
          console.warn('[secure-wizard] could not parse vault iframe URL origin:', e);
        }
        console.log('[secure-wizard] vault capture session ready, iframe origin:', vaultOrigin);
        vaultSessionReady = true;
        document.getElementById('vault-iframe').src = iframeUrl;
        if (callback) callback();
      } else {
        console.error('[secure-wizard] create_vault_session failed:', json.error);
        $('#secure-error').text(json.error || 'Failed to load card form.').show();
      }
    },
    error: function(xhr, status) {
      console.error('[secure-wizard] create_vault_session request failed:', status, xhr.status);
      vaultSessionLoading = false;
      $('#vault-loading').hide();
      $('#secure-error').text('Failed to connect to payment service. Please try again.').show();
    }
  });
}

function goToStep(step) {
  if (step === 3 && !isAddressComplete()) {
    $('#step2-error').text('Please fill in all required billing address fields.').show();
    return;
  }
  $('#step2-error').hide();

  if (step !== 3) stopCardPolling();

  // Hide all steps
  $('#step-1, #step-2, #step-3').hide();
  $('#step-' + step).show();

  // Update step badges
  for (var i = 1; i <= 3; i++) {
    var badge = document.getElementById('badge-' + i);
    badge.className = 'badge rounded-pill step-badge ' + (i === step ? 'bg-primary' : (i < step ? 'bg-success' : 'bg-secondary'));
  }

  if (step === 3) {
    if (hasCard()) {
      // Already has a card - show summary + secure button immediately
      updateCardDisplay();
    } else {
      // No card yet - create vault session and show iframe
      loadVaultSession(function() { updateCardDisplay(); });
    }
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

$(function() {
  $('input[name="date_choice"]').on('change', function() {
    $('#waitlist-dates').toggle(this.value === 'waitlist');
  });
});

function isAddressComplete() {
  return document.getElementById('address1').value.trim()
      && document.getElementById('city').value.trim()
      && document.getElementById('region').value.trim()
      && document.getElementById('zip_code').value.trim()
      && document.getElementById('country').value;
}

function hasCard() {
  return !!cardToken;
}

function cardSummaryText() {
  if (cardLastFour) {
    return (cardType ? cardType + ' ' : '') + 'ending in ' + cardLastFour;
  }
  return 'Credit card stored';
}

function updateCardDisplay() {
  var card = hasCard();
  var editing = $('#vault-iframe-container').data('showIframe');

  $('#card-summary, #vault-iframe-container, #secure-btn, #vault-loading').hide();

  if (card && !editing) {
    stopCardPolling();
    $('#card-summary-text').text(cardSummaryText());
    $('#card-summary').show();
    $('#secure-btn').show();
  } else if (vaultSessionReady) {
    $('#vault-iframe-container').show();
    if (card) {
      $('#card-summary-text').text(cardSummaryText());
      $('#card-summary').show();
    }
    // While the capture iframe is up, poll for the token landing
    // server-side (via the vault webhook) in case the iframe's
    // postMessage never reaches us.
    startCardPolling();
  }
}

var cardPollTimer = null;

function startCardPolling() {
  if (cardPollTimer) return;
  console.debug('[secure-wizard] starting card_status polling');
  cardPollTimer = setInterval(function() {
    $.ajax({
      url: 'card_status',
      method: 'GET',
      data: { assignment_id: secureWizardConfig.assignmentId },
      success: function(json) {
        if (json.error) {
          console.warn('[secure-wizard] card_status poll returned error:', json.error);
          return;
        }
        // Only adopt a token that differs from what we already have, so
        // the change-card flow isn't cancelled by its own old card.
        if (json.has_card && json.token && json.token !== cardToken) {
          console.log('[secure-wizard] card token arrived server-side (via webhook); securing room');
          cardToken = json.token;
          cardLastFour = json.last_four || '';
          cardType = json.card_type || '';
          $('#vault-iframe-container').data('showIframe', false);
          autoSecureRoom();
        }
      },
      error: function(xhr, status) {
        console.debug('[secure-wizard] card_status poll request failed:', status, xhr.status);
      }
    });
  }, 3000);
}

function stopCardPolling() {
  if (cardPollTimer) {
    console.debug('[secure-wizard] stopping card_status polling');
    clearInterval(cardPollTimer);
    cardPollTimer = null;
  }
}

$('#change-card-btn').on('click', function() {
  $('#vault-iframe-container').data('showIframe', true);
  // Reset so loadVaultSession creates a fresh capture endpoint
  iframeUrl = null;
  vaultSessionReady = false;
  loadVaultSession(function() {
    document.getElementById('vault-iframe').src = iframeUrl;
    updateCardDisplay();
  });
});

var secureSubmitInFlight = false;

// Fresh capture path: the card form was just submitted, the address was
// already validated on step 2, so finish securing without another click.
function autoSecureRoom() {
  if (secureSubmitInFlight) return;
  console.log('[secure-wizard] auto-securing room with captured card');
  stopCardPolling();
  $('#card-summary, #vault-iframe-container, #secure-btn').hide();
  $('#step3-back-btn').prop('disabled', true);
  $('#secure-progress').show();
  submitWithExistingCard();
}

// Securing failed: persist the token anyway (so the card survives a
// reload and the webhook has a row to attach metadata to), then fall
// back to the card summary + manual Secure Room button.
function secureFailed(messageText) {
  secureSubmitInFlight = false;
  $('#secure-progress').hide();
  $('#step3-back-btn').prop('disabled', false);
  $('#secure-btn').prop('disabled', false);
  $.ajax({
    url: 'save_card_token',
    method: 'POST',
    data: {
      assignment_id: secureWizardConfig.assignmentId,
      token: cardToken,
      csrf_token: csrf_token
    },
    success: function(response) {
      if (response.success) {
        console.log('[secure-wizard] card token saved for manual retry');
      } else {
        console.error('[secure-wizard] save_card_token failed:', response.error);
      }
    },
    error: function(xhr, status) {
      console.error('[secure-wizard] save_card_token request failed:', status, xhr.status);
    }
  });
  $('#secure-error').text(messageText).show();
  updateCardDisplay();
}

function submitWithExistingCard() {
  if (secureSubmitInFlight) return;
  secureSubmitInFlight = true;
  $('#secure-error').hide();
  $('#secure-btn').prop('disabled', true);

  $.ajax({
    url: 'secure_room_callback',
    method: 'POST',
    data: {
      assignment_id: secureWizardConfig.assignmentId,
      token: cardToken,
      address1: document.getElementById('address1').value.trim(),
      address2: document.getElementById('address2').value.trim(),
      city: document.getElementById('city').value.trim(),
      region: document.getElementById('region').value.trim(),
      zip_code: document.getElementById('zip_code').value.trim(),
      country: document.getElementById('country').value,
      hotel_rewards_number: document.getElementById('hotel_rewards_number').value.trim(),
      // Connector rooms render `date_choice` as a hidden input (no
      // radio / waitlist date pickers), so fall back to the plain
      // value and guard the optional date fields.
      date_choice: ($('input[name="date_choice"]:checked').val()
                    || $('input[name="date_choice"]').val() || 'accept'),
      requested_checkin: (document.getElementById('requested_checkin') || {}).value || '',
      requested_checkout: (document.getElementById('requested_checkout') || {}).value || '',
      csrf_token: csrf_token
    },
    success: function(response) {
      if (response.success) {
        console.log('[secure-wizard] room secured, redirecting');
        $('#card-summary, #vault-iframe-container, #secure-btn, #step3-back-btn, #secure-progress').hide();
        $('#secure-success').show();
        setTimeout(function() {
          window.location.href = secureWizardConfig.redirectUrl;
        }, 2000);
      } else {
        console.error('[secure-wizard] secure_room_callback failed:', response.error);
        secureFailed(response.error || 'An error occurred.');
      }
    },
    error: function(xhr, status) {
      console.error('[secure-wizard] secure_room_callback request failed:', status, xhr.status);
      secureFailed('There was an error securing your room. Please try again or contact us for assistance.');
    }
  });
}

window.addEventListener('message', function(event) {
  // Only accept messages from the vault iframe origin
  if (vaultOrigin && event.origin !== vaultOrigin) {
    // Browser extensions and other embeds also post messages, so this
    // fires routinely - but if capture succeeds and nothing happens,
    // a vault message being dropped HERE is the prime suspect.
    console.debug('[secure-wizard] ignoring message from', event.origin,
                  '(expected', vaultOrigin + ')');
    return;
  }

  var data = event.data;
  console.log('[secure-wizard] message from vault iframe (' + event.origin + '), type:',
              typeof data);
  // PCI Vault's hosted capture form posts JSON-encoded strings
  if (typeof data === 'string') {
    try { data = JSON.parse(data); } catch (e) {
      console.warn('[secure-wizard] unparseable string message from vault iframe:',
                   data.length > 200 ? data.slice(0, 200) + '…' : data);
      return;
    }
  }
  if (!data || typeof data !== 'object') {
    console.warn('[secure-wizard] non-object message from vault iframe:', data);
    return;
  }

  console.log('[secure-wizard] vault message keys:', Object.keys(data).join(', '));

  var height = data.height || (data.data && data.data.height);
  if (height) {
    console.debug('[secure-wizard] resize request from vault iframe:', height);
    document.getElementById('vault-iframe').style.height =
        Math.max(800, parseInt(height, 10) || 0) + 'px';
    return;
  }

  // The token's location varies by form/message version
  var token = data.token || (data.data && data.data.token)
      || (data.token_info && data.token_info.token);
  if (token) {
    console.log('[secure-wizard] card token received via postMessage - securing room');
    cardToken = token;
    cardLastFour = '';
    cardType = '';
    $('#vault-iframe-container').data('showIframe', false);
    autoSecureRoom();
  } else if (data.error) {
    console.error('[secure-wizard] error message from vault iframe:', data.error);
    $('#secure-error').text(data.error).show();
  } else {
    // A message from the vault origin that carries neither a token nor
    // an error - if the flow stalls after "Card successfully captured",
    // this log line shows the shape we failed to recognize.
    console.warn('[secure-wizard] unrecognized message from vault iframe; keys:',
                 Object.keys(data).join(', '), '- waiting on webhook poll instead');
  }
});
