SUPERCLRVER_sub_shape = {
    "car": ["suv", "wagon", "minivan", "sedan", "truck", "addi", "car"],
    "bus": ["articulated", "regular", "double", "school", "bus"],
    "motorbike": ["chopper", "dirtbike", "scooter", "cruiser", "motorbike"],
    "aeroplane": ["jet", "fighter", "biplane", "airliner", "aeroplane"],
    "bicycle": ["road", "utility", "mountain", "tandem", "bicycle"],
}

inverse_shape = {}
for key, value in SUPERCLRVER_sub_shape.items():
    for v in value:
        inverse_shape[v] = key

class Spatial457_utils:
    def __init__(self):

        return

    def get_random_answer(self, gt):
        import random

        all_attributes = {
            "size": ["small", "large"],
            "shape": [
                "airliner",
                "dirtbike",
                "road bike",
                "tandem bike",
                "suv",
                "wagon",
                "scooter",
                "mountain bike",
                "minivan",
                "sedan",
                "school bus",
                "fighter",
                "chopper",
                "double bus",
                "truck",
                "articulated bus",
                "cruiser",
                "jet",
                "utility bike",
                "regular bus",
                "biplane",
            ],
            "color": [
                "gray",
                "blue",
                "purple",
                "brown",
                "green",
                "cyan",
                "red",
                "yellow",
            ],
            "direction": ["left", "right", "front", "back"],
        }

        gt = gt.lower()
        if gt in ["yes", "no"]:
            return random.choice(["yes", "no"])
        if gt in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
            return str(random.randint(0, 9))
        for key, value in all_attributes.items():
            if gt in value:
                return random.choice(value)
    
    def loose_match(self, a, b):
        a = str(a).strip().lower()
        b = str(b).strip().lower()

        def remove_articles(s):
            return re.sub(r'\b(the|a|an)\b', '', s, flags=re.I).strip()

        a = remove_articles(a)
        b = remove_articles(b)

        a = re.sub(r'\s+', ' ', a)
        b = re.sub(r'\s+', ' ', b)

        synonym_map = {
            "yes": "true", "no": "false",
            "correct": "true", "incorrect": "false",
            "right": "true", "wrong": "false"
        }
        a = synonym_map.get(a, a)
        b = synonym_map.get(b, b)

        return a == b

    def all_answers(self):
        all_attributes = {
            "size": ["small", "large"],
            "shape": ["airliner", "dirtbike", "road bike", "tandem bike", "suv",
                      "wagon", "scooter", "mountain bike", "minivan", "sedan",
                      "school bus", "fighter", "chopper", "double bus", "truck",
                      "articulated bus", "cruiser", "jet", "utility bike",
                      "regular bus", "biplane"],
            "color": ["gray", "blue", "purple", "brown", "green", "cyan", "red", "yellow"],
            "direction": ["left", "right", "front", "back"],
        }

        all_answers = []
        for value in all_attributes.values():
            all_answers.extend([v.capitalize() for v in value])
        return ", ".join(all_answers)

    def is_correct(self, answer, predict):
        text2num = {
            "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
            "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
        }

        predict = str(predict).strip()
        answer  = str(answer).strip()

        if predict.lower() == "none":
            predict = "no"

        # 
        if self.loose_match(predict, answer):
            return True

        # 
        if predict == "0" and answer.lower() == "no":
            return True
        if predict.lower() in text2num and text2num[predict.lower()] == answer.lower():
            return True
        if answer.lower() == "yes" and predict in [str(i) for i in range(1, 10)]:
            return True

        # 
        if self.category_correct(predict, answer):
            return True

        return False

    def category_correct(self, answer, gt_answer):
        answer = str(answer).lower().split(" ")[0]
        gt_answer = str(gt_answer).lower().split(" ")[0]

        if (
            answer in inverse_shape
            and gt_answer in inverse_shape
            and inverse_shape[answer] == inverse_shape[gt_answer]
        ):
            return True

        return False