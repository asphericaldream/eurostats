# Image rights

Who owns the images this project downloads, what we may do with them, and what
to use on the public site instead. This is a working summary for a
non-commercial fan site, not legal advice. Checked October 2026.

Every downloaded image has a row in `images.csv` with its source URL, what it
shows, the seasons it was used, the rights holder and the licence, so any image
can be traced and removed later.

## What we download

| Image | Where it comes from | Who holds the rights |
|---|---|---|
| Club crests (89 clubs, current crest only) | EuroLeague feed, hosted on `media-cdn.incrowdsports.com` and `media-cdn.cortextech.io` | Each club. A crest is a registered trademark and usually also a copyrighted artwork. |
| Player headshots and action photos (about 1,250 people, from 2015-16) | Same feed and hosts | The photos are commissioned by Euroleague Basketball, so the copyright sits with EuroLeague or its photographers and agencies. Each player also has personality (image) rights, which in Spain, France, Italy, Greece and other EU countries limit how a recognisable face can be used. Players often license these through their club or EuroLeague. |
| Head coach photos | Same feed and hosts | Same as player photos. Other staff have no photos in the feed. |

## What is allowed

**Private use (now):** downloading and viewing them on Ilan's own machine to
build the site is fine. EuroLeague's terms allow personal, non-commercial use
of its content, and EU copyright exceptions cover private copies.

**Public site (later):** not without permission, even with no ads or income.

- Crests: showing a club's crest next to its name to identify it is common
  practice and a trademark claim is unlikely, but the crest artwork is still
  copyrighted and EuroLeague's terms forbid reusing its content. Ask first.
- Photos: copyright plus image rights, and no fair-use defence in the EU. Do
  not publish without a licence.
- Facts about a club or player (names, city, height, birth date) are not
  copyrighted and are fine to show.

## Public-safe fallbacks

1. **Club identity without crests.** Show the club name in its colours, for
   example a coloured badge with the short name ("Efes", "Real Madrid"). Colours
   and names are not protected the way the artwork is.
2. **Photos from Wikimedia Commons.** Many EuroLeague players have photos on
   Commons under CC BY or CC BY-SA. Each needs the author's name, the licence
   and a link next to the photo, and CC BY-SA images keep that licence. Use the
   Commons API to pull the licence and author with each file and store them in
   the same `images.csv` columns. Commons (`upload.wikimedia.org`,
   `commons.wikimedia.org`) is blocked in the cloud environment today, so this
   has to run on Ilan's machine or after those hosts are allowed.
3. **No photo at all.** A silhouette or initials avatar for anyone without a
   licensed photo.
4. **Crest logos on Wikimedia Commons** are mostly marked as non-free or as
   trademarks, so they do not solve the crest question.

## Draft: image section of the permission email to EuroLeague

Not sent. To go into the single permission email that also covers the data.

> **Images.** We would also like to show club crests and player and coach
> headshots from your official feed on the site, at small sizes next to club
> and player names, always with credit to Euroleague Basketball and a link to
> euroleaguebasketball.net. The site is free, has no advertising and makes no
> money. We would not edit the images or use them in anything promotional.
>
> Could you tell us whether this is acceptable, and on what terms? If crests
> or player images need separate approval from the clubs or the players'
> representatives, we would be grateful for a pointer to the right contact.
> If you prefer that we do not use them, we will show club names and colours
> instead of crests and use only openly licensed photos.
