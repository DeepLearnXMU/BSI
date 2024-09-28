from tqdm import tqdm
import ujson as json
import pdb
import os
from collections import defaultdict

docred_rel2id = json.load(open('./data/rel2id.json', 'r'))
ner2id=json.load(open('./data/ner2id.json', 'r'))
cdr_rel2id = {'1:NR:2': 0, '1:CID:2': 1}
gda_rel2id = {'1:NR:2': 0, '1:GDA:2': 1}
ner2char = {0:"&",1:"*",2:"#",3:"$",4:"@",5:"^",6:"%"}

def chunks(l, n):
    res = []
    for i in range(0, len(l), n):
        assert len(l[i:i + n]) == n
        res += [l[i:i + n]]
    return res


def read_docred(file_in, tokenizer, max_seq_length=1024,save_file=""):
    i_line = 0
    pos_samples = 0
    neg_samples = 0
    features = []
    if file_in == "":
        return None

    if os.path.exists(save_file):
        with open(file=save_file, mode='rb') as fr:
            features = json.load(fr)
        print('load preprocessed data from {}.'.format(save_file))
    else:
        with open(file_in, "r") as fh:
            data = json.load(fh)

        for sample in tqdm(data, desc="Example"):
            entities = sample['vertexSet']
            entity_start, entity_end = {}, {}
            for s_i,entity in  enumerate(entities):
                for mention in entity:
                    sent_id = mention["sent_id"]
                    pos = mention["pos"]
                    Type=mention["type"]
                    entity_start[(sent_id, pos[0])] = s_i + 7
                    entity_end[(sent_id, pos[1] - 1)] = ner2id[Type]

            Sentence_index = []
            sents = []
            entity_ids = []
            sent_map = []
            for i_s, sent in enumerate(sample['sents']):
                new_map = {}
                start_sent=len(sents)
                start_type=0
                for i_t, token in enumerate(sent):
                    tokens_wordpiece = tokenizer.tokenize(token)
                    entity_id = [start_type]*len(tokens_wordpiece)
                    if (i_s, i_t) in entity_start:
                        tokens_wordpiece = ["[unused%d]"%(entity_start[(i_s, i_t)])] + tokens_wordpiece
                        entity_id = [entity_start[(i_s, i_t)]] * len(tokens_wordpiece)
                        start_type=entity_start[(i_s, i_t)]
                    if (i_s, i_t) in entity_end:
                        tokens_wordpiece = tokens_wordpiece + ["[unused%d]"%(entity_end[(i_s, i_t)])]
                        entity_id = [entity_end[(i_s, i_t)]] * len(tokens_wordpiece)
                        start_type = 0
                    new_map[i_t] = len(sents)
                    sents.extend(tokens_wordpiece)
                    entity_ids.extend(entity_id)

                new_map[i_t + 1] = len(sents)
                sent_map.append(new_map)
                end_sent=len(sents)
                Sentence_index.append([start_sent+1,end_sent+1])

            train_triple = {}
            if "labels" in sample:
                for label in sample['labels']:
                    evidence = label['evidence']
                    r = int(docred_rel2id[label['r']])
                    if (label['h'], label['t']) not in train_triple:
                        train_triple[(label['h'], label['t'])] = [
                            {'relation': r, 'evidence': evidence}]
                    else:
                        train_triple[(label['h'], label['t'])].append(
                            {'relation': r, 'evidence': evidence})

            entity_pos = []
            entity_sentence=[]
            entity_type=[]
            for e in entities:
                entity_type.append(ner2id[e[0]["type"]])
                entity_pos.append([])
                entity_sentence.append([])
                for m in e:
                    start = sent_map[m["sent_id"]][m["pos"][0]]
                    end = sent_map[m["sent_id"]][m["pos"][1]]
                    entity_pos[-1].append((start, end,m["sent_id"],))
                    entity_sentence[-1].append(m["sent_id"])


            relations, hts ,evidence_list= [], [],[]
            head_sentence, tail_sentence,ht_sentence = [], [],[]
            for h, t in train_triple.keys():
                relation = [0] * len(docred_rel2id)
                head_sentence.append(list(set(entity_sentence[h])))
                tail_sentence.append(list(set(entity_sentence[t])))
                evidence=[]
                for mention in train_triple[h, t]:
                    relation[mention["relation"]] = 1
                    evidence.extend(mention["evidence"])
                evidence_list.append(list(set(evidence)))
                ht_sentence.append(list(set(evidence_list[-1]+tail_sentence[-1]+head_sentence[-1])))
                relations.append(relation)
                hts.append([h, t])
                pos_samples += 1

            for h in range(len(entities)):
                for t in range(len(entities)):
                    if h != t and [h, t] not in hts:
                        relation = [1] + [0] * (len(docred_rel2id) - 1)
                        relations.append(relation)
                        head_sentence.append(list(set(entity_sentence[h])))
                        tail_sentence.append(list(set(entity_sentence[t])))
                        evidence_list.append([])
                        ht_sentence.append(list(set(tail_sentence[-1] + head_sentence[-1])))
                        hts.append([h, t])
                        neg_samples += 1

            assert len(relations) == len(entities) * (len(entities) - 1)

            sents = sents[:max_seq_length - 2]
            entity_ids = entity_ids[:max_seq_length - 2]
            input_ids = tokenizer.convert_tokens_to_ids(sents)
            input_ids = tokenizer.build_inputs_with_special_tokens(input_ids)

            entity_ids = [0] + entity_ids + [0]
            i_line += 1
            feature = {'input_ids': input_ids,
                       'entity_pos': entity_pos,
                       'entity_ids':entity_ids,
                       'labels': relations,
                       'hts': hts,
                       'title': sample['title'],
                       "entity_type": entity_type,
                       "Sentence_index":Sentence_index,
                       }
            features.append(feature)

        print("# of documents {}.".format(i_line))
        print("# of positive examples {}.".format(pos_samples))
        print("# of negative examples {}.".format(neg_samples))

        json_str = json.dumps(features)
        with open(save_file, 'w') as json_file:
            json_file.write(json_str)

    return features


def read_cdr(file_in, tokenizer, max_seq_length=1024):
    pmids = set()
    features = []
    maxlen = 0
    with open(file_in, 'r') as infile:
        lines = infile.readlines()
        for i_l, line in enumerate(tqdm(lines)):
            line = line.rstrip().split('\t')
            pmid = line[0]

            if pmid not in pmids:
                pmids.add(pmid)
                text = line[1]
                prs = chunks(line[2:], 17)

                ent2idx = {}
                train_triples = {}

                entity_pos = set()
                for p in prs:
                    es = list(map(int, p[8].split(':')))
                    ed = list(map(int, p[9].split(':')))
                    tpy = p[7]
                    for start, end in zip(es, ed):
                        entity_pos.add((start, end, tpy))

                    es = list(map(int, p[14].split(':')))
                    ed = list(map(int, p[15].split(':')))
                    tpy = p[13]
                    for start, end in zip(es, ed):
                        entity_pos.add((start, end, tpy))

                sents = [t.split(' ') for t in text.split('|')]
                new_sents = []
                sent_map = {}
                i_t = 0
                for sent in sents:
                    for token in sent:
                        tokens_wordpiece = tokenizer.tokenize(token)
                        for start, end, tpy in list(entity_pos):
                            if i_t == start:
                                tokens_wordpiece = ["*"] + tokens_wordpiece
                            if i_t + 1 == end:
                                tokens_wordpiece = tokens_wordpiece + ["*"]
                        sent_map[i_t] = len(new_sents)
                        new_sents.extend(tokens_wordpiece)
                        i_t += 1
                    sent_map[i_t] = len(new_sents)
                sents = new_sents

                entity_pos = []

                for p in prs:
                    if p[0] == "not_include":
                        continue
                    if p[1] == "L2R":
                        h_id, t_id = p[5], p[11]
                        h_start, t_start = p[8], p[14]
                        h_end, t_end = p[9], p[15]
                    else:
                        t_id, h_id = p[5], p[11]
                        t_start, h_start = p[8], p[14]
                        t_end, h_end = p[9], p[15]
                    h_start = map(int, h_start.split(':'))
                    h_end = map(int, h_end.split(':'))
                    t_start = map(int, t_start.split(':'))
                    t_end = map(int, t_end.split(':'))
                    h_start = [sent_map[idx] for idx in h_start]
                    h_end = [sent_map[idx] for idx in h_end]
                    t_start = [sent_map[idx] for idx in t_start]
                    t_end = [sent_map[idx] for idx in t_end]
                    if h_id not in ent2idx:
                        ent2idx[h_id] = len(ent2idx)
                        entity_pos.append(list(zip(h_start, h_end)))
                    if t_id not in ent2idx:
                        ent2idx[t_id] = len(ent2idx)
                        entity_pos.append(list(zip(t_start, t_end)))
                    h_id, t_id = ent2idx[h_id], ent2idx[t_id]

                    r = cdr_rel2id[p[0]]
                    if (h_id, t_id) not in train_triples:
                        train_triples[(h_id, t_id)] = [{'relation': r}]
                    else:
                        train_triples[(h_id, t_id)].append({'relation': r})

                relations, hts = [], []
                for h, t in train_triples.keys():
                    relation = [0] * len(cdr_rel2id)
                    for mention in train_triples[h, t]:
                        relation[mention["relation"]] = 1
                    relations.append(relation)
                    hts.append([h, t])

            maxlen = max(maxlen, len(sents))
            sents = sents[:max_seq_length - 2]
            input_ids = tokenizer.convert_tokens_to_ids(sents)
            input_ids = tokenizer.build_inputs_with_special_tokens(input_ids)

            if len(hts) > 0:
                feature = {'input_ids': input_ids,
                           'entity_pos': entity_pos,
                           'labels': relations,
                           'hts': hts,
                           'title': pmid,
                           }
                features.append(feature)
    print("Number of documents: {}.".format(len(features)))
    print("Max document length: {}.".format(maxlen))
    return features


def read_gda(file_in, tokenizer, max_seq_length=1024):
    pmids = set()
    features = []
    maxlen = 0
    with open(file_in, 'r') as infile:
        lines = infile.readlines()
        for i_l, line in enumerate(tqdm(lines)):
            line = line.rstrip().split('\t')
            pmid = line[0]

            if pmid not in pmids:
                pmids.add(pmid)
                text = line[1]
                prs = chunks(line[2:], 17)

                ent2idx = {}
                train_triples = {}

                entity_pos = set()
                for p in prs:
                    es = list(map(int, p[8].split(':')))
                    ed = list(map(int, p[9].split(':')))
                    tpy = p[7]
                    for start, end in zip(es, ed):
                        entity_pos.add((start, end, tpy))

                    es = list(map(int, p[14].split(':')))
                    ed = list(map(int, p[15].split(':')))
                    tpy = p[13]
                    for start, end in zip(es, ed):
                        entity_pos.add((start, end, tpy))

                sents = [t.split(' ') for t in text.split('|')]
                new_sents = []
                sent_map = {}
                i_t = 0
                for sent in sents:
                    for token in sent:
                        tokens_wordpiece = tokenizer.tokenize(token)
                        for start, end, tpy in list(entity_pos):
                            if i_t == start:
                                tokens_wordpiece = ["*"] + tokens_wordpiece
                            if i_t + 1 == end:
                                tokens_wordpiece = tokens_wordpiece + ["*"]
                        sent_map[i_t] = len(new_sents)
                        new_sents.extend(tokens_wordpiece)
                        i_t += 1
                    sent_map[i_t] = len(new_sents)
                sents = new_sents

                entity_pos = []

                for p in prs:
                    if p[0] == "not_include":
                        continue
                    if p[1] == "L2R":
                        h_id, t_id = p[5], p[11]
                        h_start, t_start = p[8], p[14]
                        h_end, t_end = p[9], p[15]
                    else:
                        t_id, h_id = p[5], p[11]
                        t_start, h_start = p[8], p[14]
                        t_end, h_end = p[9], p[15]
                    h_start = map(int, h_start.split(':'))
                    h_end = map(int, h_end.split(':'))
                    t_start = map(int, t_start.split(':'))
                    t_end = map(int, t_end.split(':'))
                    h_start = [sent_map[idx] for idx in h_start]
                    h_end = [sent_map[idx] for idx in h_end]
                    t_start = [sent_map[idx] for idx in t_start]
                    t_end = [sent_map[idx] for idx in t_end]
                    if h_id not in ent2idx:
                        ent2idx[h_id] = len(ent2idx)
                        entity_pos.append(list(zip(h_start, h_end)))
                    if t_id not in ent2idx:
                        ent2idx[t_id] = len(ent2idx)
                        entity_pos.append(list(zip(t_start, t_end)))
                    h_id, t_id = ent2idx[h_id], ent2idx[t_id]

                    r = gda_rel2id[p[0]]
                    if (h_id, t_id) not in train_triples:
                        train_triples[(h_id, t_id)] = [{'relation': r}]
                    else:
                        train_triples[(h_id, t_id)].append({'relation': r})

                relations, hts = [], []
                for h, t in train_triples.keys():
                    relation = [0] * len(gda_rel2id)
                    for mention in train_triples[h, t]:
                        relation[mention["relation"]] = 1
                    relations.append(relation)
                    hts.append([h, t])

            maxlen = max(maxlen, len(sents))
            sents = sents[:max_seq_length - 2]
            input_ids = tokenizer.convert_tokens_to_ids(sents)
            input_ids = tokenizer.build_inputs_with_special_tokens(input_ids)

            if len(hts) > 0:
                feature = {'input_ids': input_ids,
                           'entity_pos': entity_pos,
                           'labels': relations,
                           'hts': hts,
                           'title': pmid,
                           }
                features.append(feature)
    print("Number of documents: {}.".format(len(features)))
    print("Max document length: {}.".format(maxlen))
    return features
