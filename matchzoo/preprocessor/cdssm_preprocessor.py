"""CDSSM Preprocessor."""

import typing
import logging
from tqdm import tqdm
import numpy as np

from matchzoo import utils
from matchzoo import engine
from matchzoo import preprocessor
from matchzoo import datapack

logger = logging.getLogger(__name__)


class CDSSMPreprocessor(engine.BasePreprocessor, preprocessor.SegmentMixin):
    """CDSSM preprocessor helper.

    Example:
        >>> train_inputs = [
        ...     ("id0", "id1", "beijing", "Beijing is capital of China", 1),
        ...     ("id0", "id2", "beijing", "China is in east Asia", 0),
        ...     ("id0", "id3", "beijing", "Summer in Beijing is hot.", 1)
        ... ]
        >>> cdssm_preprocessor = CDSSMPreprocessor()
        >>> rv_train = cdssm_preprocessor.fit_transform(
        ...     train_inputs,
        ...     stage='train')
        >>> type(rv_train)
        <class 'matchzoo.datapack.DataPack'>
        >>> test_inputs = [("id0",
        ...                 "id4",
        ...                 "beijing",
        ...                 "I visted beijing yesterday.")]
        >>> rv_test = cdssm_preprocessor.fit_transform(
        ...     test_inputs,
        ...     stage='test')
        >>> type(rv_test)
        <class 'matchzoo.datapack.DataPack'>
    """

    def __init__(self, sliding_window: int=3, window_nb: int=5,
                 pad_value: int=0, pad_mode: str='pre',
                 truncate_mode: str='pre'):
        """Initialization.

        :param sliding_window: sliding window length.
        :param window_nb: sliding window number.
        :param pad_value: filling text with :attr:`pad_value` if
         text length is smaller than assumed.
        :param pad_mode: String, `pre` or `post`:
            pad either before or after each sequence.
        :param truncate_mode: String, `pre` or `post`:
            remove values from sequences larger than assumed,
            either at the beginning or at the end of the sequences.
        """
        self.datapack = None
        self._window = sliding_window
        self._window_nb = window_nb
        self._pad_value = pad_value
        self._pad_mode = pad_mode
        self._truncate_mode = truncate_mode
        self._text_length = window_nb + sliding_window - 1

    def _prepare_process_units(self) -> list:
        """Prepare needed process units."""
        return [
            preprocessor.TokenizeUnit(),
            preprocessor.LowercaseUnit(),
            preprocessor.PuncRemovalUnit(),
            preprocessor.StopRemovalUnit(),
        ]

    def fit(self, inputs: typing.List[tuple]):
        """
        Fit pre-processing context for transformation.

        Can be simplified by compute vocabulary term and index.

        :param inputs: Inputs to be preprocessed.
        :return: class:`CDSSMPreprocessor` instance.
        """
        vocab = []
        units = self._prepare_process_units()
        units.append(preprocessor.NgramLetterUnit())

        logger.info("Start building vocabulary & fitting parameters.")

        # Convert user input into a datapack object.
        self.datapack = self.segment(inputs, stage='train')

        for idx, row in tqdm(self.datapack.left.iterrows()):
            # For each piece of text, apply process unit sequentially.
            text = row.text_left
            for unit in units:
                text = unit.transform(text)
            vocab.extend(text)

        for idx, row in tqdm(self.datapack.right.iterrows()):
            text = row.text_right
            for unit in units:
                text = unit.transform(text)
            vocab.extend(text)

        # Initialize a vocabulary process unit to build letter-ngram vocab.
        vocab_unit = preprocessor.VocabularyUnit()
        vocab_unit.fit(vocab)

        # Store the fitted parameters in context.
        self.datapack.context['term_index'] = vocab_unit.state['term_index']
        dim = (len(vocab_unit.state['term_index']) + 1)
        self.datapack.context['dims'] = dim
        self.datapack.context['input_shapes'] = [(self._window_nb,
                                                  dim * self._window),
                                                 (self._window_nb,
                                                  dim * self._window)]
        return self

    @utils.validate_context
    def transform(
        self,
        inputs: typing.List[tuple],
        stage: str
    ) -> datapack.DataPack:
        """
        Apply transformation on data, create `letter-trigram` representation.

        :param inputs: Inputs to be preprocessed.
        :param stage: Pre-processing stage, `train` or `test`.

        :return: Transformed data as :class:`DataPack` object.
        """
        if stage == 'test':
            self.datapack = self.segment(inputs, stage=stage)

        # prepare pipeline unit.
        units = self._prepare_process_units()
        ngram_unit = preprocessor.NgramLetterUnit()
        hash_unit = preprocessor.WordHashingUnit(
            self.datapack.context['term_index'])
        text_length = self._text_length * self.datapack.context['dims']
        fix_unit = preprocessor.FixedLengthUnit(
            text_length, self._pad_value, self._pad_mode, self._truncate_mode)
        slide_unit = preprocessor.SlidingWindowUnit(self._window)

        logger.info(f"Start processing input data for {stage} stage.")

        for idx, row in tqdm(self.datapack.left.iterrows()):
            text = row.text_left
            for unit in units:
                text = unit.transform(text)
            text = [ngram_unit.transform([term]) for term in text]
            text = [hash_unit.transform(term) for term in text]
            text = np.array(text).flatten()
            text = fix_unit.transform(text.tolist())
            text = np.reshape(text, (self._text_length, -1))
            text = slide_unit.transform(text.tolist())
            self.datapack.left.at[idx, 'text_left'] = text

        for idx, row in tqdm(self.datapack.right.iterrows()):
            text = row.text_right
            for unit in units:
                text = unit.transform(text)
            text = [ngram_unit.transform([term]) for term in text]
            text = [hash_unit.transform(term) for term in text]
            text = np.array(text).flatten()
            text = fix_unit.transform(text.tolist())
            text = np.reshape(text, (self._text_length, -1))
            text = slide_unit.transform(text.tolist())
            self.datapack.right.at[idx, 'text_right'] = text

        return self.datapack
