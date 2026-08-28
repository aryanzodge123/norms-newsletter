/* The blog copy, and the only place it is written.
 *
 * Same contract as faq-content.js. Four things read this file: the /blog
 * index, the post document itself, the BlogPosting and Blog JSON-LD, and the
 * Links block in llms.txt. All four are composed from these strings at build
 * time rather than restated beside them, because a hand-maintained copy of
 * text that changes is a copy that stops being true.
 *
 * Plain strings, not JSX, for the same reason: the same words go into the
 * rendered page, into JSON-LD and into a plain-text file untouched. So the
 * curly quotes and apostrophes are real characters, never entities.
 *
 * No em dashes (CLAUDE.md rule 7).
 *
 * `body` is a list of blocks rather than one blob of markup, because the page
 * sets three of them differently and nothing here should carry a class name.
 *   text  an ordinary paragraph
 *   pull  the one line that gets the rules above and below it
 *   close the last two lines, set in the display face
 * Structured data and llms.txt read the `text` field of every block regardless
 * of kind, so the machine-readable copy is the whole post and not a subset.
 */

export const POSTS = [
  {
    slug: 'put-my-phone-down',
    title: 'I built a newsletter so I could put my phone down',
    /* The standing subtitle. It is the page's meta description too, so it has
       to work read alone, with no headline above it. */
    dek:
      'I wanted to log off without falling behind. It turned out the thing standing in the ' +
      'way was not my attention span, it was the shape of the news itself.',
    date: '2026-08-28',
    dateLabel: 'August 28, 2026',
    author: 'Aryan Zodge',
    /* Stated rather than computed. 790 words at the 200 a minute a reader of
       this actually manages, rounded to the honest number. */
    minutes: 4,
    body: [
      {
        kind: 'text',
        text:
          'I used to get my news the way a lot of people get their news, which is to say I ' +
          'didn’t really get it at all. I got it in pieces, between other pieces, usually late ' +
          'at night with the lights already off. It was a habit before it was ever a routine, ' +
          'and I knew it wasn’t a good one.',
      },
      {
        kind: 'text',
        text:
          'The part that bothered me wasn’t the time, though there was a lot of that. It was ' +
          'that at the end of an hour I couldn’t tell you one thing I had learned. I would put ' +
          'the phone down with the distinct feeling of having been informed, and if you had ' +
          'asked me about a single story I would have come up empty. Something was happening in ' +
          'that hour. It just wasn’t that.',
      },
      {
        kind: 'text',
        text:
          'So I wanted to log off. The problem was that logging off meant falling behind, and I ' +
          'didn’t want that either. I wanted both things at once, which in my experience is ' +
          'usually the moment right before you start building something.',
      },
      {
        kind: 'text',
        text:
          'This is the point where a reasonable person subscribes to a newsletter. There are ' +
          'good ones. But the thing I kept catching on is the shape of the news itself. The same ' +
          'story lands in five places on the same morning, and each one tells me most of what ' +
          'the last one already did. Going source to source to assemble one clear picture is ' +
          'tedious, and it is the same tedious work tomorrow, and the day after that. At some ' +
          'point it stopped feeling like a reading problem and started feeling like an ' +
          'engineering problem. If five outlets are covering one story, something should be able ' +
          'to notice that, fold them into a single thing, and hand it to me already made.',
      },
      {
        kind: 'text',
        text:
          'I do data and AI engineering for a living, so that part was my cup of tea. I built it ' +
          'over about a month, mostly at night, in the hours after work. I am the kind of person ' +
          'who writes everything down, so my notes app spent that month permanently open, ' +
          'collecting ideas at whatever hour they showed up.',
      },
      {
        kind: 'text',
        text:
          'The first time it ran end to end was the night before I expected it to work at all. I ' +
          'sat there smiling cheek to cheek at what was, objectively, a folder full of text. But ' +
          'it felt like the real thing. Four topics I actually cared about, AI, cybersecurity, ' +
          'technology and business, collected and sorted and written up while I was asleep.',
      },
      {
        kind: 'text',
        text:
          'Since then it has arrived every morning around nine, and I listen to the podcast ' +
          'version while I get ready. That is the whole thing. That is what I wanted.',
      },
      {
        kind: 'text',
        text:
          'It is not flawless. For a good while the audio build sat in front of the publish step, ' +
          'which meant that if the podcast failed, the newsletter it was attached to didn’t go ' +
          'out. There was a fallback, so there were still stories to read, but I want to be clear ' +
          'about how silly that is. The fun part could stop the useful part from shipping. It is ' +
          'on the list. Everything is on some list.',
      },
      {
        kind: 'text',
        text:
          'What made it stop being only mine was a screenshot. I had shown a friend what I ' +
          'built, the way you show someone a thing you are a little proud of and a little ' +
          'embarrassed by. Some time later he sent me a picture of that morning’s edition and ' +
          'told me he had been listening to the podcast while doing his laundry. He had ' +
          'bookmarked it. He was just using it, on an ordinary weekday, without me in the room.',
      },
      {
        kind: 'pull',
        text:
          'That was the moment I saw the potential. Not a newsletter I read, but something that ' +
          'could go a lot further.',
      },
      {
        kind: 'text',
        text:
          'Reading something you made every single day teaches you what it isn’t. I started ' +
          'noticing the questions the newsletter couldn’t answer. What if I could say how long I ' +
          'wanted it to be today. What if the topics weren’t my four, but yours, whatever yours ' +
          'happen to be. What if, when a story landed that I only half understood, I could just ' +
          'ask about it, and keep asking until I actually did.',
      },
      {
        kind: 'text',
        text:
          'That last one is the one I can’t stop thinking about. Being able to talk to the news ' +
          'might be the best way there is to understand it.',
      },
      {
        kind: 'text',
        text:
          'So that is Norm. The name started as the editor, the one running the newsroom in my ' +
          'head, and it has quietly become the name of the whole thing. Same idea as the ' +
          'newsletter, except curated for you instead of for me.',
      },
      {
        kind: 'close',
        text: 'The newsletter still runs every morning. I still listen while I get ready.',
      },
      {
        kind: 'close',
        text:
          'This is just the beginning, and there is so much more to come. I’m glad you’re here ' +
          'for the ride.',
      },
    ],
  },
]

/* The index renders newest first and the post document looks itself up by
   slug. One post makes both trivial and neither is worth getting wrong later. */
export const postBySlug = (slug) => POSTS.find((p) => p.slug === slug)
