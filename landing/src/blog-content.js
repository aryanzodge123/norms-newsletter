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
    slug: 'how-do-you-get-your-news',
    title: 'How do you get your news?',
    dek:
      'Search, feeds, newsletters and apps all get you the news. Almost none of them ever ' +
      'tell you when you’re done.',
    date: '2026-09-19',
    dateLabel: 'September 19, 2026',
    author: 'Aryan Zodge',
    minutes: 4,
    body: [
      {
        kind: 'text',
        text:
          'I don’t remember choosing how I get my news. I doubt you do either.',
      },
      {
        kind: 'text',
        text:
          'Mine went something like this. A friend sent me a link, so I read it. Later I ' +
          'searched for something, and read a few more. I signed up for a newsletter because it ' +
          'looked good. I installed an app for one big story and never deleted it. None of that ' +
          'was a decision. It just piled up, and one day it was how I got my news.',
      },
      {
        kind: 'text',
        text:
          'What I noticed was how it felt. I’d pick up my phone, spend twenty minutes reading, ' +
          'and put it down unsure what I’d learned. I’d read a lot. I just couldn’t say what I ' +
          'was now caught up on.',
      },
      {
        kind: 'text',
        text:
          'So I started paying attention to how news actually reaches people. There are a ' +
          'handful of ways, and each is good at something.',
      },
      {
        kind: 'text',
        text:
          'The most common is the single article. Someone shares it, or a search finds it, and ' +
          'you read it. It’s easy, and it costs nothing to start. But you didn’t choose it. ' +
          'Something decided it was the article to show you, and that something is usually ' +
          'rewarded for your click, not for whether you understood anything. Each article also ' +
          'arrives alone, with none of the story around it. You get one piece of a puzzle and ' +
          'never see the box.',
      },
      {
        kind: 'text',
        text:
          'Then there’s RSS, which is the way of people who want control. You pick the ' +
          'sources, and everything they publish lands in one place. I have real respect for it. ' +
          'But RSS gives you everything, in the order it arrived, with nothing ranked. There’s ' +
          'no such thing as caught up. The unread count just climbs until reading the news feels ' +
          'like clearing a debt.',
      },
      {
        kind: 'text',
        text:
          'Newsletters are the calm option. A person picks the stories and writes them up, and ' +
          'it shows up in your inbox. That’s a real improvement. But it’s one person’s taste, ' +
          'sent to everyone, so you get their idea of what matters. Subscribe to a few and ' +
          'you’ll find the same big story in each one, explained three times.',
      },
      {
        kind: 'text',
        text:
          'News apps are the fastest of all. They tell you the moment something happens, which ' +
          'sounds like what you’d want. But an app is judged on how often you open it. Its ' +
          'alerts are built to pull you back, not to let you leave.',
      },
      {
        kind: 'pull',
        text: 'Each of these is built to be kept open. None of them is built to be finished.',
      },
      {
        kind: 'text',
        text:
          'That’s what took me a while to see. The problem isn’t that there’s too little news. ' +
          'There’s more than anyone could read in a lifetime. The problem is that nothing tells ' +
          'you when you’re done, and nothing knows what you actually care about. So you keep ' +
          'going, because stopping feels like missing something.',
      },
      {
        kind: 'text',
        text: 'That’s the problem Norm is built to solve.',
      },
      {
        kind: 'text',
        text:
          'You start by picking your topics, and then you decide how much each one matters. ' +
          'Care a lot about technology and only a little about business? Your newsletter is ' +
          'divided that way. It’s not a general edition sent to everyone. It’s yours, and the ' +
          'weights you set decide how much room each topic gets.',
      },
      {
        kind: 'text',
        text:
          'Norm also reads for you. When several outlets cover the same story, Norm brings them ' +
          'together into one, so you read it once instead of three times. That one change ' +
          'removes most of the repetition I used to feel.',
      },
      {
        kind: 'text',
        text:
          'Then there’s the part I care about most. You decide how long your newsletter is, and ' +
          'when it’s done, it’s done. There’s no feed underneath and nothing to scroll into. ' +
          'You reach the end and you get to stop, knowing you’ve seen what mattered to you. ' +
          'Being finished is the whole point.',
      },
      {
        kind: 'text',
        text:
          'It also arrives when you want it. You choose the time, and the news waits for you, ' +
          'not the other way around. No alert is trying to get your attention.',
      },
      {
        kind: 'text',
        text:
          'And I didn’t want any of this to ask for blind trust. So every story links back to ' +
          'the original sources it came from. If a summary makes you curious, you can go read ' +
          'the real thing. If something sounds off, you can check it yourself. Norm gives you ' +
          'the short version and never gets in the way of the long one.',
      },
      {
        kind: 'text',
        text:
          'That’s really the whole idea. You shouldn’t have to read everything to feel ' +
          'informed, and you shouldn’t need to keep watching for fear of missing something.',
      },
      { kind: 'close', text: 'Keep up without keeping watch.' },
      { kind: 'close', text: 'Read it, and be done.' },
    ],
  },
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

/* The index renders in POSTS order, so a new post goes at the top of the array.
   The post document looks itself up by slug. */
export const postBySlug = (slug) => POSTS.find((p) => p.slug === slug)
