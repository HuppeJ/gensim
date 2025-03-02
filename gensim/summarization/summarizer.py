#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Licensed under the GNU LGPL v2.1 - http://www.gnu.org/licenses/lgpl.html

"""This module provides functions for summarizing texts. Summarizing is based on
ranks of text sentences using a variation of the TextRank algorithm [1]_.

.. [1] Federico Barrios, Federico L´opez, Luis Argerich, Rosita Wachenchauzer (2016).
       Variations of the Similarity Function of TextRank for Automated Summarization,
       https://arxiv.org/abs/1602.03606


Data
----

.. data:: INPUT_MIN_LENGTH - Minimal number of sentences in text
.. data:: WEIGHT_THRESHOLD - Minimal weight of edge between graph nodes. Smaller weights set to zero.

Example
-------

.. sourcecode:: pycon

    >>> from gensim.summarization.summarizer import summarize
    >>> text = '''Rice Pudding - Poem by Alan Alexander Milne
    ... What is the matter with Mary Jane?
    ... She's crying with all her might and main,
    ... And she won't eat her dinner - rice pudding again -
    ... What is the matter with Mary Jane?
    ... What is the matter with Mary Jane?
    ... I've promised her dolls and a daisy-chain,
    ... And a book about animals - all in vain -
    ... What is the matter with Mary Jane?
    ... What is the matter with Mary Jane?
    ... She's perfectly well, and she hasn't a pain;
    ... But, look at her, now she's beginning again! -
    ... What is the matter with Mary Jane?
    ... What is the matter with Mary Jane?
    ... I've promised her sweets and a ride in the train,
    ... And I've begged her to stop for a bit and explain -
    ... What is the matter with Mary Jane?
    ... What is the matter with Mary Jane?
    ... She's perfectly well and she hasn't a pain,
    ... And it's lovely rice pudding for dinner again!
    ... What is the matter with Mary Jane?'''
    >>> print(summarize(text))
    And she won't eat her dinner - rice pudding again -
    I've promised her dolls and a daisy-chain,
    I've promised her sweets and a ride in the train,
    And it's lovely rice pudding for dinner again!

"""

import logging
from gensim.utils import deprecated
from gensim.summarization.pagerank_weighted import pagerank_weighted as _pagerank
from gensim.summarization.textcleaner import clean_text_by_sentences as _clean_text_by_sentences
from gensim.summarization.commons import build_graph as _build_graph
from gensim.summarization.commons import remove_unreachable_nodes as _remove_unreachable_nodes
from gensim.summarization.bm25 import iter_bm25_bow as _bm25_weights
from gensim.corpora import Dictionary
from math import log10 as _log10
from six.moves import range


INPUT_MIN_LENGTH = 2

WEIGHT_THRESHOLD = 1.e-3

logger = logging.getLogger(__name__)


def _set_graph_edge_weights(graph):
    """Sets weights using BM25 algorithm. Leaves small weights as zeroes. If all weights are fairly small,
     forces all weights to 1, inplace.

    Parameters
    ----------
    graph : :class:`~gensim.summarization.graph.Graph`
        Given graph.

    """
    documents = graph.nodes()
    weights = _bm25_weights(documents)

    for i, doc_bow in enumerate(weights):
        if i % 1000 == 0 and i > 0:
            logger.info('PROGRESS: processing %s/%s doc (%s non zero elements)', i, len(documents), len(doc_bow))

        for j, weight in doc_bow:
            if i == j or weight < WEIGHT_THRESHOLD:
                continue

            edge = (documents[i], documents[j])

            if not graph.has_edge(edge):
                graph.add_edge(edge, weight)

    # Handles the case in which all similarities are zero.
    # The resultant summary will consist of random sentences.
    if all(graph.edge_weight(edge) == 0 for edge in graph.iter_edges()):
        _create_valid_graph(graph)


def _create_valid_graph(graph):
    """Sets all weights of edges for different edges as 1, inplace.

    Parameters
    ----------
    graph : :class:`~gensim.summarization.graph.Graph`
        Given graph.

    """
    nodes = graph.nodes()

    for i in range(len(nodes)):
        for j in range(len(nodes)):
            if i == j:
                continue

            edge = (nodes[i], nodes[j])

            if graph.has_edge(edge):
                graph.del_edge(edge)

            graph.add_edge(edge, 1)


@deprecated("Function will be removed in 4.0.0")
def _get_doc_length(doc):
    """Get length of (tokenized) document.

    Parameters
    ----------
    doc : list of (list of (tuple of int))
        Given document.

    Returns
    -------
    int
        Length of document.

    """
    return sum(item[1] for item in doc)


@deprecated("Function will be removed in 4.0.0")
def _get_similarity(doc1, doc2, vec1, vec2):
    """Returns similarity of two documents.

    Parameters
    ----------
    doc1 : list of (list of (tuple of int))
        First document.
    doc2 : list of (list of (tuple of int))
        Second document.
    vec1 : array
        ? of first document.
    vec1 : array
        ? of secont document.

    Returns
    -------
    float
        Similarity of two documents.

    """
    numerator = vec1.dot(vec2.transpose()).toarray()[0][0]
    length_1 = _get_doc_length(doc1)
    length_2 = _get_doc_length(doc2)

    denominator = _log10(length_1) + _log10(length_2) if length_1 > 0 and length_2 > 0 else 0

    return numerator / denominator if denominator != 0 else 0


def _build_corpus(sentences):
    """Construct corpus from provided sentences.

    Parameters
    ----------
    sentences : list of :class:`~gensim.summarization.syntactic_unit.SyntacticUnit`
        Given sentences.

    Returns
    -------
    list of list of (int, int)
        Corpus built from sentences.

    """
    split_tokens = [sentence.token.split() for sentence in sentences]
    dictionary = Dictionary(split_tokens)
    return [dictionary.doc2bow(token) for token in split_tokens]


def _get_important_sentences(sentences, corpus, important_docs):
    """Get most important sentences.

    Parameters
    ----------
    sentences : list of :class:`~gensim.summarization.syntactic_unit.SyntacticUnit`
        Given sentences.
    corpus : list of list of (int, int)
        Provided corpus.
    important_docs : list of list of (int, int)
        Most important documents of the corpus.

    Returns
    -------
    list of :class:`~gensim.summarization.syntactic_unit.SyntacticUnit`
        Most important sentences.

    """
    hashable_corpus = _build_hasheable_corpus(corpus)
    sentences_by_corpus = dict(zip(hashable_corpus, sentences))
    return [sentences_by_corpus[tuple(important_doc)] for important_doc in important_docs]


def _get_sentences_with_word_count(sentences, word_count):
    """Get list of sentences. Total number of returned words close to specified `word_count`.

    Parameters
    ----------
    sentences : list of :class:`~gensim.summarization.syntactic_unit.SyntacticUnit`
        Given sentences.
    word_count : int or None
        Number of returned words. If None full most important sentences will be returned.

    Returns
    -------
    list of :class:`~gensim.summarization.syntactic_unit.SyntacticUnit`
        Most important sentences.

    """
    length = 0
    selected_sentences = []

    # Loops until the word count is reached.
    for sentence in sentences:
        words_in_sentence = len(sentence.text.split())

        # Checks if the inclusion of the sentence gives a better approximation
        # to the word parameter.
        if abs(word_count - length - words_in_sentence) > abs(word_count - length):
            return selected_sentences

        selected_sentences.append(sentence)
        length += words_in_sentence

    return selected_sentences

def _get_group_of_best_sentences(sentences, nb_sentences):
    set_of_selected_sentences = set()
    # add first sentence
    set_of_selected_sentences.add(sentences[0])

    i = 1
    count = 1
    while count <= nb_sentences and i < len(sentences):
        if sentences[i] not in set_of_selected_sentences:
            set_of_selected_sentences.add(sentences[i])
            count = count + 1
        i = i + 1

    return list(set_of_selected_sentences)

def _extract_important_sentences(sentences, corpus, important_docs, word_count, nb_sentences):
    """Get most important sentences of the `corpus`.

    Parameters
    ----------
    sentences : list of :class:`~gensim.summarization.syntactic_unit.SyntacticUnit`
        Given sentences.
    corpus : list of list of (int, int)
        Provided corpus.
    important_docs : list of list of (int, int)
        Most important docs of the corpus.
    word_count : int
        Number of returned words. If None full most important sentences will be returned.
    nb_sentences : int
        Number of returned sentences. 

    Returns
    -------
    list of :class:`~gensim.summarization.syntactic_unit.SyntacticUnit`
        Most important sentences.

    """
    important_sentences = _get_important_sentences(sentences, corpus, important_docs)

    # If no "word_count" option is provided, the number of sentences is
    # reduced by the provided ratio. Else, the ratio is ignored.
    if word_count is not None:
        return _get_sentences_with_word_count(important_sentences, word_count)
    elif nb_sentences is not None: 
        return _get_group_of_best_sentences(important_sentences, nb_sentences)
    else:
        return important_sentences \

def _format_results(extracted_sentences, split):
    """Returns `extracted_sentences` in desired format.

    Parameters
    ----------
    extracted_sentences : list of :class:~gensim.summarization.syntactic_unit.SyntacticUnit
        Given sentences.
    split : bool
        If True sentences will be returned as list. Otherwise sentences will be merged and returned as string.

    Returns
    -------
    list of str
        If `split` **OR**
    str
        Formatted result.

    """
    if split:
        return [sentence.text for sentence in extracted_sentences]
    return "\n".join(sentence.text for sentence in extracted_sentences)


def _build_hasheable_corpus(corpus):
    """Hashes and get `corpus`.

    Parameters
    ----------
    corpus : list of list of (int, int)
        Given corpus.

    Returns
    -------
    list of list of (int, int)
        Hashable corpus.

    """
    return [tuple(doc) for doc in corpus]


def summarize_corpus(corpus, ratio=0.2):
    """Get a list of the most important documents of a corpus using a variation of the TextRank algorithm [1]_.
     Used as helper for summarize :func:`~gensim.summarization.summarizer.summarizer`

    Note
    ----
    The input must have at least :const:`~gensim.summarization.summarizer.INPUT_MIN_LENGTH` documents for the summary
    to make sense.


    Parameters
    ----------
    corpus : list of list of (int, int)
        Given corpus.
    ratio : float, optional
        Number between 0 and 1 that determines the proportion of the number of
        sentences of the original text to be chosen for the summary, optional.

    Returns
    -------
    list of str
        Most important documents of given `corpus` sorted by the document score, highest first.

    """
    hashable_corpus = _build_hasheable_corpus(corpus)

    # If the corpus is empty, the function ends.
    if len(corpus) == 0:
        logger.warning("Input corpus is empty.")
        return []

    # Warns the user if there are too few documents.
    if len(corpus) < INPUT_MIN_LENGTH:
        logger.warning("Input corpus is expected to have at least %d documents.", INPUT_MIN_LENGTH)

    logger.info('Building graph')
    graph = _build_graph(hashable_corpus)

    logger.info('Filling graph')
    _set_graph_edge_weights(graph)

    logger.info('Removing unreachable nodes of graph')
    _remove_unreachable_nodes(graph)

    # Cannot calculate eigenvectors if number of unique documents in corpus < 3.
    # Warns user to add more text. The function ends.
    if len(graph.nodes()) < 3:
        logger.warning("Please add more sentences to the text. The number of reachable nodes is below 3")
        return []

    logger.info('Pagerank graph')
    pagerank_scores = _pagerank(graph)

    logger.info('Sorting pagerank scores')
    hashable_corpus.sort(key=lambda doc: pagerank_scores.get(doc, 0), reverse=True)

    return [list(doc) for doc in hashable_corpus[:int(len(corpus) * ratio)]]


def summarize(text, ratio=0.2, word_count=None, nb_sentences=None, split=False):
    """Get a summarized version of the given text.

    The output summary will consist of the most representative sentences
    and will be returned as a string, divided by newlines.

    Note
    ----
    The input should be a string, and must be longer than :const:`~gensim.summarization.summarizer.INPUT_MIN_LENGTH`
    sentences for the summary to make sense.
    The text will be split into sentences using the split_sentences method in the :mod:`gensim.summarization.texcleaner`
    module. Note that newlines divide sentences.


    Parameters
    ----------
    text : str
        Given text.
    ratio : float, optional
        Number between 0 and 1 that determines the proportion of the number of
        sentences of the original text to be chosen for the summary.
    word_count : int or None, optional
        Determines how many words will the output contain.
        If more than one parameter is provided, the parameter selected will be selected in this order: ratio > word_count > nb_sentences
    nb_sentences: int or None, optional
        Determines how many sentences will the output contain.
        If more than one parameter is provided, the parameter selected will be selected in this order: ratio > word_count > nb_sentences
    split : bool, optional
        If True, list of sentences will be returned. Otherwise joined
        strings will bwe returned.

    Returns
    -------
    list of str
        If `split` **OR**
    str
        Most representative sentences of given the text.

    """
    # Gets a list of processed sentences.
    sentences = _clean_text_by_sentences(text)

    # If no sentence could be identified, the function ends.
    if len(sentences) == 0:
        logger.warning("Input text is empty.")
        return [] if split else u""

    # If only one sentence is present, the function raises an error (Avoids ZeroDivisionError).
    if len(sentences) == 1:
        raise ValueError("input must have more than one sentence")

    # Warns if the text is too short.
    if len(sentences) < INPUT_MIN_LENGTH:
        logger.warning("Input text is expected to have at least %d sentences.", INPUT_MIN_LENGTH)

    corpus = _build_corpus(sentences)
    
    # Modified code
    ratio_value = ratio
    if word_count is not None or nb_sentences is not None:
        ratio_value = 1

    most_important_docs = summarize_corpus(corpus, ratio=ratio_value)

    # If couldn't get important docs, the algorithm ends.
    if not most_important_docs:
        logger.warning("Couldn't get relevant sentences.")
        return [] if split else u""

    # Extracts the most important sentences with the selected criterion.
    extracted_sentences = _extract_important_sentences(sentences, corpus, most_important_docs, word_count, nb_sentences)

    # Sorts the extracted sentences by apparition order in the original text.
    # extracted_sentences.sort(key=lambda s: s.index)

    # return _format_results(extracted_sentences, split)

    return extracted_sentences
