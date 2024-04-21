import re
import unicodedata
import zipfile
from io import BytesIO
import requests
import torch
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader, Dataset


def download_and_extract(lang1, lang2):
    url = f"http://www.manythings.org/anki/{lang1}-{lang2}.zip"
    extract_to = f"data/{lang1}-{lang2}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise Exception(
            f"Failed to download data, status code: {r.status_code}, url: {url}"
        )
    z = zipfile.ZipFile(BytesIO(r.content))
    z.extractall(extract_to)


class LangDataset(Dataset):
    def __init__(self, pairs, input_lang, output_lang, device, eos_token):
        self.pairs = pairs
        self.input_lang = input_lang
        self.output_lang = output_lang
        self.device = device
        self.eos_token = eos_token

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, idx):
        inputs, targets = self.pairs[idx]
        input_tensor = self.tensor_from_sentence(self.input_lang, inputs)
        target_tensor = self.tensor_from_sentence(self.output_lang, targets)
        return input_tensor, target_tensor

    def tensor_from_sentence(self, lang, sentence):
        indexes = lang.encode(sentence)
        indexes.append(self.eos_token)
        tensor = torch.tensor(indexes, dtype=torch.long, device=self.device)
        return tensor


def load_data(
    seed,
    lang1,
    lang2,
    test_size,
    sos_token_id,
    eos_token_id,
    max_length,
    device,
    batch_size,
):
    download_and_extract(lang1, lang2)
    input_lang, output_lang, pairs = prepare_data(
        lang1, lang2, sos_token_id, eos_token_id, max_length, reverse=True
    )
    X = [i[0] for i in pairs]
    y = [i[1] for i in pairs]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=seed
    )
    train_pairs = list(zip(X_train, y_train))
    test_pairs = list(zip(X_test, y_test))
    # return train_pairs, test_pairs, input_lang, output_lang
    # make dataloaders
    train_dataset = LangDataset(
        train_pairs, input_lang, output_lang, device, eos_token_id
    )
    test_dataset = LangDataset(
        test_pairs, input_lang, output_lang, device, eos_token_id
    )
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False)
    return train_loader, test_loader, input_lang, output_lang


class Lang:
    def __init__(self, name, sos_token_id, eos_token_id):
        self.name = name
        self.sos_token_id = sos_token_id
        self.eos_token_id = eos_token_id
        self.word2index = {}
        self.word2count = {}
        self.index2word = {sos_token_id: "SOS", eos_token_id: "EOS"}
        self.n_words = 2  # Count SOS and EOS

    def add_sentence(self, sentence):
        for word in sentence.split(" "):
            self.add_word(word)

    def add_word(self, word):
        if word not in self.word2index:
            self.word2index[word] = self.n_words
            self.word2count[word] = 1
            self.index2word[self.n_words] = word
            self.n_words += 1
        else:
            self.word2count[word] += 1

    def encode(self, sentence):
        return [self.word2index[word] for word in sentence.split(" ")]

    def decode(self, tensor):
        return " ".join([self.index2word[i.item()] for i in tensor])


def unicode_to_ascii(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def normalize_string(s):
    s = unicode_to_ascii(s.lower().strip())
    s = re.sub(r"([.!?])", r" \1", s)
    s = re.sub(r"[^a-zA-Z.!?]+", r" ", s)
    return s


def read_langs(lang1, lang2, sos_token_id, eos_token_id, reverse=False):
    print("Reading lines...")
    lines = (
        open(f"data/{lang1}-{lang2}/{lang1}.txt", encoding="utf-8")
        .read()
        .strip()
        .split("\n")
    )
    pairs = [[normalize_string(s) for s in l.split("\t")[:2]] for l in lines]
    if reverse:
        pairs = [list(reversed(p)) for p in pairs]
        input_lang = Lang(lang2, sos_token_id=sos_token_id, eos_token_id=eos_token_id)
        output_lang = Lang(lang1, sos_token_id=eos_token_id, eos_token_id=eos_token_id)
    else:
        input_lang = Lang(lang1, sos_token_id=sos_token_id, eos_token_id=eos_token_id)
        output_lang = Lang(lang2, sos_token_id=eos_token_id, eos_token_id=eos_token_id)
    return input_lang, output_lang, pairs


eng_prefixes = (
    "i am",
    "i m",
    "he is",
    "he s",
    "she is",
    "she s",
    "you are",
    "you re",
    "we are",
    "we re",
    "they are",
    "they re",
)


def filter_pair(p, max_length):
    return (
        len(p[0].split(" ")) < max_length
        and len(p[1].split(" ")) < max_length
        and p[1].startswith(eng_prefixes)
    )


def filter_pairs(pairs, max_length):
    return [pair for pair in pairs if filter_pair(pair, max_length=max_length)]


def prepare_data(lang1, lang2, sos_token_id, eos_token_id, max_length, reverse=False):
    input_lang, output_lang, pairs = read_langs(
        lang1, lang2, reverse, sos_token_id, eos_token_id
    )
    print("Read %s sentence pairs" % len(pairs))
    pairs = filter_pairs(pairs, max_length)
    print("Trimmed to %s sentence pairs" % len(pairs))
    print("Counting words...")
    for pair in pairs:
        input_lang.add_sentence(pair[0])
        output_lang.add_sentence(pair[1])
    print("Counted words:")
    print(input_lang.name, input_lang.n_words)
    print(output_lang.name, output_lang.n_words)
    return input_lang, output_lang, pairs
