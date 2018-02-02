[![Build Status](https://travis-ci.org/rams/barcode.svg)](https://travis-ci.org/rams/barcode) [![Coverage Status](https://coveralls.io/repos/github/rams/barcode/badge.svg?branch=master)](https://coveralls.io/github/rams/barcode?branch=master)

RAMS Core plugin: Barcode
==============

supports barcode generation / scanning and support functions for ubersystem


setup
==========
set the following vars in your development.ini:

a secret 10-digit key (KEEP THIS SAFE, SHARE WITH NO-ONE) used to encrypt/decrypt barcodes
```
barcode_key = "ABCDEF1234"
```

a secret numeric salt value (KEEP THIS SAFE, SHARE WITH NO-ONE) used to encrypt/decrypt barcodes
pick a random number between 0 and max of 1,000,000 (don't go over)
```
barcode_salt = 121212
```

a 1-byte event-ID number embedded in each barcode that tells us what event this came from
```
barcode_event_id = 2
```


barcode theory
==============

A barcode contains a ```badge_number``` and an ```event_id```. The event_id is just a unique ID that is used for verification purposes.

These are symetrically encrypted with a salt into a 6-character ```barcode_number``` which is printed on the badge itself.  It might look like this: ```aXv5bC```  This is a CODE-128 compliant encoding.

If you have a barcode number, you need the key and salt to decrypt it, which will yield the badge number and the event ID.  Ubersystem installations can do this, but normal users can't generate a badge number and event ID from a barcode, and vice versa.

An attacker won't be able to generate a valid barcode number without the secret key, salt, and event_id.

looking up barcodes
===================

If you have a barcode and want to know the badge#, call get_badge_num_from_barcode():
```
badge_num = get_badge_num_from_barcode(barocde_num='ABC123')
```

If you have a badge number and want to generate a barcode from it, call generate_barcode_from_badge_num()
```
barcode = generate_barcode_from_badge_num(badge_num=3)
```

These numbers are encrypted/decrypted using the secret key, salt, and event_id in the INI file.  RAMS doesn't need to store a list of barcodes anywhere since this can be computed anytime it's needed.
