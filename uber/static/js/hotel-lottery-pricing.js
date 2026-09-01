// Room pricing on the lottery entry form. Recomputes stay totals as the
// entrant changes their preferred dates or the occupancy dropdown.
//
// The nightly rate resolution here must match uber.hotel.pricing.price_for:
// most specific cell first, then night-only, then occupancy-only, then the
// block's base rate. A night with no rate anywhere makes the whole total
// unavailable rather than being treated as free.

document.addEventListener('alpine:init', function () {
  Alpine.data('hotelPricing', function () {
    return {
      config: window.hotelPricingConfig || {hotels: [], occupancy: {min: 1, max: 1}},
      occupancy: 1,
      checkIn: '',
      checkOut: '',

      init: function () {
        var self = this;
        var opts = this.occupancyOptions();
        this.occupancy = opts.length ? opts[0] : 1;

        // The date fields are plain WTForms inputs outside this component,
        // so bind them directly rather than through x-model.
        [['earliest_checkin_date', 'checkIn'],
         ['latest_checkout_date', 'checkOut']].forEach(function (pair) {
          var el = document.getElementById(pair[0]);
          if (!el) { return; }
          self[pair[1]] = el.value;
          ['change', 'input'].forEach(function (evt) {
            el.addEventListener(evt, function () { self[pair[1]] = el.value; });
          });
        });

        // The hotel and room type ranking cards live in a later step, outside
        // this component, so they are updated imperatively.
        ['occupancy', 'checkIn', 'checkOut'].forEach(function (prop) {
          self.$watch(prop, function () { self.updateRankingPrices(); });
        });
        this.$nextTick(function () { self.updateRankingPrices(); });
      },

      // Every block of one hotel, or every block of one room type across all
      // hotels, depending on which ranking is being priced.
      blocksForHotel: function (hotelId) {
        var hotel = this.config.hotels.filter(function (h) { return h.id === hotelId; })[0];
        return hotel ? hotel.blocks : [];
      },

      blocksForType: function (typeId) {
        var out = [];
        this.config.hotels.forEach(function (hotel) {
          hotel.blocks.forEach(function (block) {
            if (block.type_id === typeId) { out.push(block); }
          });
        });
        return out;
      },

      totalsRangeText: function (blocks) {
        var self = this;
        var totals = blocks.filter(function (b) { return self.blockFits(b); })
          .map(function (b) { return self.blockTotal(b); })
          .filter(function (t) { return t !== null; });
        if (!totals.length) { return null; }
        var low = Math.min.apply(null, totals);
        var high = Math.max.apply(null, totals);
        return low === high ? this.money(low) + ' total'
                            : this.money(low) + ' - ' + this.money(high) + ' total';
      },

      // Swap each ranking card's static price range for the total this
      // entrant would actually pay. Falls back to the server-rendered range
      // whenever there is nothing to compute from.
      updateRankingPrices: function () {
        var self = this;
        [['hotel_preference', this.blocksForHotel],
         ['room_type_preference', this.blocksForType],
         ['suite_type_preference', this.blocksForType]].forEach(function (pair) {
          var fieldId = pair[0];
          var lookup = pair[1];
          ['selected_' + fieldId, 'deselected_' + fieldId].forEach(function (listId) {
            var list = document.getElementById(listId);
            if (!list) { return; }
            Array.from(list.children).forEach(function (li) {
              var priceEl = li.querySelector('.ranking-price');
              if (!priceEl) { return; }
              if (priceEl.dataset.baseText === undefined) {
                priceEl.dataset.baseText = priceEl.textContent;
              }
              var text = self.hasDates()
                ? self.totalsRangeText(lookup.call(self, li.dataset.choice))
                : null;
              priceEl.textContent = text || priceEl.dataset.baseText;
            });
          });
        });
      },

      occupancyOptions: function () {
        var out = [];
        var range = this.config.occupancy || {min: 1, max: 1};
        for (var n = range.min; n <= range.max; n++) { out.push(n); }
        return out.length ? out : [1];
      },

      hasDates: function () {
        return Boolean(this.checkIn && this.checkOut && this.nights().length);
      },

      nights: function () {
        if (!this.checkIn || !this.checkOut) { return []; }
        var start = new Date(this.checkIn + 'T00:00:00');
        var end = new Date(this.checkOut + 'T00:00:00');
        if (isNaN(start) || isNaN(end) || end <= start) { return []; }
        var out = [];
        for (var d = new Date(start); d < end; d.setDate(d.getDate() + 1)) {
          out.push(d.toISOString().slice(0, 10));
        }
        return out;
      },

      nightCount: function () { return this.nights().length; },

      rateSet: function (block) {
        return (this.config.show_staff_rates && block.rates.staff)
          ? block.rates.staff : block.rates.public;
      },

      // Mirrors price_for's fallback chain. Returns null when unpriced.
      cellPrice: function (rates, nightIso, occupancy) {
        var nightKey = rates.per_night ? nightIso : '';
        var occKey = rates.per_occupancy ? String(occupancy) : '';
        var byNight = rates.cells[nightKey] || rates.cells[''] || {};
        var value = byNight[occKey];
        if (value === undefined || value === null) { value = byNight['']; }
        if (value === undefined || value === null) { value = rates.base; }
        if (value === undefined || value === null) { return null; }
        return parseFloat(value);
      },

      blockTotal: function (block) {
        var rates = this.rateSet(block);
        if (!rates) { return null; }
        var nights = this.nights();
        if (!nights.length) { return null; }
        var total = 0;
        for (var i = 0; i < nights.length; i++) {
          var rate = this.cellPrice(rates, nights[i], this.occupancy);
          if (rate === null) { return null; }
          total += rate;
        }
        return total;
      },

      // Blocks that cannot hold this many people are not offered at all.
      blockFits: function (block) {
        return this.occupancy >= block.min_capacity && this.occupancy <= block.capacity;
      },

      money: function (amount) {
        if (amount === null || amount === undefined) { return ''; }
        return '$' + (amount % 1 === 0 ? amount.toFixed(0) : amount.toFixed(2));
      },

      blockTotalText: function (block) {
        if (!this.blockFits(block)) {
          return 'not available for ' + this.occupancy +
            (this.occupancy === 1 ? ' person' : ' people');
        }
        var total = this.blockTotal(block);
        return total === null ? 'rate not published' : this.money(total) + ' total';
      },

      hotelRangeText: function (hotel) {
        var self = this;
        var totals = hotel.blocks.filter(function (b) { return self.blockFits(b); })
          .map(function (b) { return self.blockTotal(b); })
          .filter(function (t) { return t !== null; });
        if (!totals.length) { return 'no rates'; }
        var low = Math.min.apply(null, totals);
        var high = Math.max.apply(null, totals);
        return low === high ? this.money(low) : this.money(low) + ' - ' + this.money(high);
      },

      // Built as a string because the shape varies per block: a single rate,
      // a row of nights, a column of occupancies, or a full grid.
      rateTable: function (hotel) {
        var self = this;
        var html = '';
        hotel.blocks.forEach(function (block) {
          var rates = self.rateSet(block);
          if (!rates) { return; }
          html += '<div class="mb-3"><div class="fw-semibold small">' +
            self.escape(block.type_name) + '</div>';
          if (block.notes) {
            html += '<div class="form-text fst-italic">' + self.escape(block.notes) + '</div>';
          }

          var nights = rates.per_night ? rates.nights : [''];
          var occupancies = rates.per_occupancy ? rates.occupancies : [''];

          html += '<div class="table-responsive"><table class="table table-sm mb-0"><thead><tr>';
          html += '<th class="small"></th>';
          nights.forEach(function (n) {
            html += '<th class="small">' + (n ? self.nightLabel(n) : 'Per night') + '</th>';
          });
          html += '</tr></thead><tbody>';
          occupancies.forEach(function (occ) {
            html += '<tr><th class="small text-nowrap">' +
              (occ === '' ? 'Any occupancy'
                          : occ + (occ === 1 ? ' person' : ' people')) + '</th>';
            nights.forEach(function (n) {
              var rate = self.cellPrice(rates, n, occ === '' ? null : occ);
              html += '<td class="small">' + (rate === null ? '-' : self.money(rate)) + '</td>';
            });
            html += '</tr>';
          });
          html += '</tbody></table></div></div>';
        });
        return html || '<p class="form-text mb-0">No rates published yet.</p>';
      },

      nightLabel: function (iso) {
        var d = new Date(iso + 'T00:00:00');
        return isNaN(d) ? iso : d.toLocaleDateString(undefined,
          {weekday: 'short', month: 'numeric', day: 'numeric'});
      },

      escape: function (text) {
        var div = document.createElement('div');
        div.textContent = text === null || text === undefined ? '' : text;
        return div.innerHTML;
      },
    };
  });
});
