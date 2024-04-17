How to test ubersystem
========================

Go to the URL where ubersystem is installed.  That would typically be http://localhost:4321/magfest/, 
or wherever someone has given you the link to.

There are 2 sides to the ubersystem accessed from the default page:
- The public facing registration side   (the 'preregister' link)
- The admin-only control side (the 'log in' link)

The default login for testing setups is:
username: magfest@example.com
password: magfest

When in test mode, you can test out credit card payments with the following fake credit card numbers from Stripe:
4242 4242 4242 4242
expiration: doesn't matter
CVC: doesn't matter

Please report any issues here:
https://github.com/EliAndrewC/magfest/issues

When reporting issues, please paste in the URL you were on, and your expected vs observed results, and
the steps you took to encounter this issue.  

Also, you can easily paste in screenshots too!  Use the windows snipping tool (Start->Accessories->Snipping Tool), 
take your screenshot, Copy, and then Ctrl+V in the Github issue tracker.  
It will automatically upload your screenshot (neat)

Example issue/bug report:
```
title: incorrect error message shown when I don't enter a phone number for a volunteer

steps:
1) fill out the prereg form on the admin side, check 'is volunteering', leave the phone number blank
2) observe the cell phone field is not marked as required
3) click Submit

observed result: 
error message: "cellphone is required"

expected result:
The page should let me submit without errors since cell phone says it's optional.

recommended fix:
Mark the cellphone field as not optional.
```
