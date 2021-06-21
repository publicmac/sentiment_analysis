from GoogleNews import GoogleNews
from influxdb import InfluxDBClient
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import configparser
import praw

# Initialize the configuration parser with the config file
conf = configparser.ConfigParser()
conf.read('app.conf')

# Load the reddit api information from the config
reddit = praw.Reddit(
    client_id=conf['reddit']['client_id'],
    client_secret=conf['reddit']['client_secret'],
    password=conf['reddit']['password'],
    user_agent=conf['reddit']['user_agent'],
    username=conf['reddit']['username']
)

# Load the database configuration info
try:
    influx = InfluxDBClient(host='localhost', port=8086)
    influx.switch_database('cryptosentry')
except:
    pass


def get_articles(term: str, period: str = "24h", pages: int = 5):
    """
    This function searches google news for articles on the provided topic, performs a sentiment analysis and filters out
    articles that are mostly neutral.

    :param term: The search term to google
    :param period: The time range to look within (defaults to 1 day)
    :param pages: The number of search result pages to consider
    :return: A list of information about articles that had a level of positive or negative sentiment
    """
    # Initialize the Google News object
    googlenews = GoogleNews()
    googlenews.set_period(period)       # Set the time period
    googlenews.setlang('en')            # Set the preferred language
    googlenews.search(term)             # Set the search term

    # Initialize the sentiment analyzer
    sid_obj = SentimentIntensityAnalyzer()

    # Initialize a list to hold the return results in
    ret = []

    # Iterate over the number of search result pages to check
    for i in range(1, pages):
        # Switch the results to the current search page
        googlenews.get_page(i)

        # Iterate over the articles on this page
        for article in googlenews.result(sort=True):
            # Analyse the sentiment of the article titles and descriptions
            sa_desc = sid_obj.polarity_scores(article['desc'])
            sa_title = sid_obj.polarity_scores(article['title'])

            # Average the title and description sentiment scores (to consider both in the final score)
            article['sentiment'] = {
                'neg': (sa_desc['neg'] + sa_title['neg']) / 2.0 if (sa_desc['neg'] + sa_title['neg']) > 0.0 else 0.0,
                'neu': (sa_desc['neu'] + sa_title['neu']) / 2.0 if (sa_desc['neu'] + sa_title['neu']) > 0.0 else 0.0,
                'pos': (sa_desc['pos'] + sa_title['pos']) / 2.0 if (sa_desc['pos'] + sa_title['pos']) > 0.0 else 0.0
            }

            # If the positive score is above 10% (0.1) and is also greater the the negative score...
            if article['sentiment']['pos'] > 0.1 and article['sentiment']['pos'] >= article['sentiment']['neg']:
                # Add a positive flair id to the article
                article['flair_id'] = "de2aaf50-d192-11eb-acd5-0ef0cae72431"

                # Add the article to the return list
                ret.append(article)

            # Otherwise if the negative score is greater than 10%, add a negative flair
            elif article['sentiment']['neg'] > 0.1:
                # Add a negative flair id to the article
                article['flair_id'] = "f35be8d0-d192-11eb-8588-0eaeb32d0d51"

                # Add the article to the return list
                ret.append(article)

    # Return the list of scored articles
    return ret


def is_article_posted(title: str, sub: str = 'CryptoSentry'):
    """
    This function checks to see if the article with the given title has already been posted

    :param title: The title of the article
    :param sub: The subreddit name to search for the article
    :return: True if article found, else False
    """
    # Initialize the return value to False (not found)
    found = False

    # Search the subreddit for the post, this will not do anything if no article is found
    for submission in reddit.subreddit(sub).search(title):
        found = True    # Indicate an article was found
        break           # Exit the loop

    # Return the found variable
    return found


def post_article(title: str, link: str, flair_id: str, sub: str = 'CryptoSentry'):
    """
    This function creates a reddit post

    :param title: The title of the post
    :param link: The link to the news article
    :param flair_id: The flair id to add to the post (obtained from mod tools in reddit)
    :param sub: The subreddit to post to
    :return: None
    """
    # Post to reddit
    reddit.subreddit(sub).submit(title, flair_id=flair_id, url=link)


def search_and_post(topics: dict = {'XLM': ['Stellar Lumens'], 'ETH': ['Ethereum'], 'ADA': ['Cardano'], 'BTC': ['Bitcoin']}, sub: str = 'CryptoSentry', write_to_db: bool = False):
    """
    Performs the search and analysis of multiple topics, checks if the results are posted and posts them if not.

    :param topics: The topics to search for. Each topic key contains a list of relevant search terms.
    :param sub: The subreddit to post to.
    :return: None
    """
    # Initialize the list of values to write to the database if enabled
    influx_data = [] if write_to_db else None

    # Iterate over the topics
    for topic, terms in topics.items():
        # Iterate over the current topics search terms
        for term in terms:
            # Get the analysed articles
            articles = get_articles(term)

            # Iterate over the articles
            for article in articles:
                try:
                    # Add the topic to the article dictionary (used for database writes)
                    article['symbol'] = topic

                    # If the article has not been posted...
                    if not is_article_posted(article['title']):
                        # Post the article
                        post_article("[%s] " % topic + article['title'], article['link'], article['flair_id'], sub)

                        # Add the article data to the insert list if database writing enabled
                        if write_to_db:
                            influx_data.append(prep_for_influx(article))
                    # If the article has been posted, provide feedback that it's being skipped
                    else:
                        print("Skipping: %s" % article['title'])
                except:
                    # If there is any issue, continue to the next article instead of exiting the program
                    continue
    # Write to the database if enabled
    if write_to_db:
        influx.write_points(influx_data)


def prep_for_influx(article: dict):
    """
    Creates a dictionary thats formatted for inserting into an InfluxDB database

    :param article: The article dictionary
    :return: The InfluxDB dictionary
    """
    return {
        "measurement": "articles",
        "tags": {
            "title": article['title'],
            "media": article['media'],
            "description": article['desc'],
            "link": article['link'],
            "img": article['img'],
            "symbol": article['symbol']
        },
        "time": article['datetime'].strftime('%Y-%m-%dT%H:%M:%SZ'),
        "fields": {
            "positive": article['sentiment']['pos'],
            "negative": article['sentiment']['neg'],
            "neutral": article['sentiment']['neu']
        }
    }


search_and_post()

