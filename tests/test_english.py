"""A store's German name for a product, in plain English (english.py), from a small word list.

What it promises: every word in the list says what the table below says; a name is put into English only when every
word of it is known, so an unknown word leaves the store's own words alone (never half a translation); a name that
is English already is not said twice; and nothing is asked of any outside service.
"""
import socket
import unittest
from unittest import mock

from wardrobe import english

# Every word in english.WORDS, with what it must say. A word added to the list needs its line here too.
EVERY_WORD = {
    "mantel": "coat", "jacke": "jacket", "bomberjacke": "bomber jacket", "windjacke": "windbreaker",
    "blazer": "blazer", "overshirt": "overshirt", "pullover": "jumper", "strickjacke": "cardigan",
    "cardigan": "cardigan", "hemd": "shirt", "t-shirt": "T-shirt", "langarmshirt": "long-sleeved top",
    "poloshirt": "polo shirt", "strickpolo": "knitted polo", "hose": "trousers", "anzughose": "suit trousers",
    "chinohose": "chinos", "chino": "chinos", "chinos": "chinos", "jeans": "jeans", "trousers": "trousers",
    "turnschuhe": "sneakers", "sneaker": "sneakers", "schuhe": "shoes", "loafer": "loafers", "loafers": "loafers",
    "derbys": "derby shoes", "derby": "derby", "boots": "boots", "stiefel": "boots", "bein": "leg",
    "kragen": "collar", "schalkragen": "shawl collar", "kapuze": "hood", "reissverschluss": "zip",
    "reißverschluss": "zip", "v-ausschnitt": "V-neck", "rundhalsausschnitt": "crew neck", "rundhals": "crew-neck",
    "falten": "pleats", "bundfalten": "pleats", "bügelfalten": "pressed creases", "taille": "waist",
    "passform": "fit", "fit": "fit", "taschendetail": "pocket detail", "stretch": "stretch",
    "gürteldetail": "belt detail", "used-details": "worn-look details", "struktur": "texture", "wolle": "wool",
    "woll": "wool", "wollmischung": "wool blend", "wollmix": "wool blend", "mix": "blend",
    "merinowolle": "merino wool", "merinowoll": "merino wool", "merino": "merino", "kaschmir": "cashmere",
    "baumwolle": "cotton", "baumwoll": "cotton", "leinen": "linen", "seide": "silk", "popeline": "poplin",
    "jersey": "jersey", "twill": "twill", "flanell": "flannel", "piqué": "piqué", "denim": "denim",
    "cord": "corduroy", "canvas": "canvas", "nylon": "nylon", "modal": "modal", "leder": "leather",
    "veloursleder": "suede", "spalt": "split", "bouclé": "bouclé", "strick": "knit", "grobstrick": "chunky-knit",
    "doubleface": "double-faced", "slub": "slub", "selvedge": "selvedge", "einreihig": "single-breasted",
    "doppelreihig": "double-breasted", "zweireihig": "double-breasted", "oversize": "oversized",
    "oversized": "oversized", "locker": "relaxed", "leger": "relaxed", "relaxt": "relaxed", "relaxed": "relaxed",
    "entspannt": "relaxed", "lässig": "casual", "boxy": "boxy", "kastig": "boxy", "klassisch": "classic",
    "classic": "classic", "regular": "regular", "normal": "regular", "slim": "slim", "schmal": "slim",
    "weit": "wide", "gerad": "straight", "barrel": "barrel", "gerippt": "ribbed", "rip": "ribbed",
    "gestrickt": "knitted", "gekocht": "boiled", "meliert": "marled", "unstrukturiert": "unstructured",
    "nahtlos": "seamless", "rein": "pure", "fein": "fine", "schwer": "heavy", "leicht": "light", "kurz": "short",
    "markant": "bold", "geschnitten": "cut", "zulaufend": "tapering", "standard": "standard", "tapered": "tapered",
    "loose": "loose", "baggy": "baggy", "straight": "straight", "heavyweight": "heavyweight",
    "midweight": "midweight", "low": "low", "oxford": "Oxford", "penny": "penny", "chelsea": "Chelsea",
    "mit": "with", "und": "and", "&": "and", "im": "in a", "in": "in",
}

# Names in the shapes the stores gave on 11 Nov (COS, Weekday), and what a customer reads.
NAMES = {
    "Einreihiger Oversize-Mantel aus Wollmischung": "Single-breasted oversized coat, wool blend",
    "Lockere Wollhose mit Geradem Bein und Falten": "Relaxed wool trousers with straight leg and pleats",
    "Hose aus Woll-Twill mit Schmal Zulaufendem Bein": "Trousers, wool twill with tapered leg",
    "Baumwoll-T-Shirt mit Rundhalsausschnitt": "Cotton T-shirt with crew neck",
    "Schmal Geschnittenes Geripptes Baumwoll-T-Shirt": "Slim-cut ribbed cotton T-shirt",
    "Schmales T-Shirt aus Baumwolle, Modal & Wolle": "Slim T-shirt, cotton, modal and wool",
    "Locker geschnittenes, kastiges Popeline-Hemd": "Relaxed-cut, boxy poplin shirt",
    "Pullover aus Reinem Kaschmir mit V-Ausschnitt": "Jumper, pure cashmere with V-neck",
    "Jacke aus Gekochter Wolle mit Schalkragen": "Jacket, boiled wool with shawl collar",
    "Grobstrickpullover mit Relaxed Fit": "Chunky-knit jumper with relaxed fit",
    "Oversized T-Shirt im kastigen Fit": "Oversized T-shirt in a boxy fit",
    "Loafers aus Spalt-Veloursleder": "Loafers, split suede",
    "Markante Derbys aus Leder": "Bold derby shoes, leather",
    "Lässige Bomberjacke": "Casual bomber jacket",
    "Klassisches Baumwollhemd": "Classic cotton shirt",
}


class EveryWord(unittest.TestCase):
    def test_every_word_in_the_list_has_its_line_here(self):
        self.assertEqual(set(english.WORDS), set(EVERY_WORD), "a word added to english.WORDS needs its line in EVERY_WORD")

    def test_every_word_says_what_it_should(self):
        for german, said in EVERY_WORD.items():
            with self.subTest(german):
                self.assertEqual(english.word(german), said)
                self.assertEqual(english.word(german.title()), said, "as stores write it, capitalised")

    def test_adjectives_with_their_german_endings(self):
        for german, said in (("Einreihiger", "single-breasted"), ("Doppelreihige", "double-breasted"),
                             ("Lockere", "relaxed"), ("Lockeres", "relaxed"), ("Lockerer", "relaxed"),
                             ("Geradem", "straight"), ("Gerade", "straight"), ("Weitem", "wide"),
                             ("Meliertem", "marled"), ("Reinem", "pure"), ("Normaler", "regular"),
                             ("Gekochter", "boiled"), ("Kastigen", "boxy"), ("Legere", "relaxed")):
            with self.subTest(german):
                self.assertEqual(english.word(german), said)

    def test_compounds_and_hyphens_are_read_part_by_part(self):
        for german, said in (("Wollhose", "wool trousers"), ("Cordhose", "corduroy trousers"),
                             ("Leinenhose", "linen trousers"), ("Strickpullover", "knit jumper"),
                             ("Rundhalspullover", "crew-neck jumper"), ("Feinstrickpullover", "fine knit jumper"),
                             ("Oversize-Mantel", "oversized coat"), ("Baumwoll-T-Shirt", "cotton T-shirt"),
                             ("Doubleface-Woll-Mix", "double-faced wool blend"), ("Barrel-Bein", "barrel leg")):
            with self.subTest(german):
                self.assertEqual(english.word(german), said)

    def test_two_words_that_mean_one_thing(self):
        self.assertEqual(english.name("Hose mit Schmal Zulaufendem Bein"), "Trousers with tapered leg")
        self.assertEqual(english.name("Schmal Geschnittenes Hemd"), "Slim-cut shirt")
        self.assertEqual(english.name("Locker geschnittenes Hemd"), "Relaxed-cut shirt")


class WholeNames(unittest.TestCase):
    def test_names_in_the_shapes_the_stores_gave(self):
        for german, said in NAMES.items():
            with self.subTest(german):
                self.assertEqual(english.name(german), said)

    def test_an_unknown_word_leaves_the_stores_own_words_alone(self):
        for german in ("Rider Jeans mit Geradem Bein und Lockerer Passform",    # "Rider", a model's name
                       "Jacke mit Racer-Ausschnitt",                             # "Racer"
                       "Fold Lockere Jeans mit Weitem Bein",
                       "Kapuzenpullover", "Wollhose mit Kapuzendetail", "Arbeitsjacke aus Canvas",
                       "Schmales T-Shirt aus Pima-Baumwolle", "Basis T-Shirt Slim-Fit /01", "Hosen",
                       "aus Wolle", "Zzz"):
            with self.subTest(german):
                self.assertIsNone(english.name(german))
        for word in ("Zzz", "Racer-Ausschnitt", "Kurzarm", "Rippjersey"):
            with self.subTest(word):
                self.assertIsNone(english.word(word))

    def test_nothing_to_say_says_nothing(self):
        for empty in (None, "", "   "):
            self.assertIsNone(english.name(empty))

    def test_a_name_in_english_already_is_not_said_twice(self):
        for name in ("Classic Boxy T-Shirt", "Oversized Blazer", "Tapered Jeans", "Chelsea-Boots"):
            with self.subTest(name):
                self.assertIsNone(english.name(name))

    def test_a_models_own_name_stays(self):
        self.assertEqual(english.name("Florian - Legere Anzughose mit Bügelfalten"),
                         "Florian – relaxed suit trousers with pressed creases")
        self.assertEqual(english.name("Bowie - T-Shirt aus Slub-Jersey mit Used-Details"),
                         "Bowie – T-shirt, slub jersey with worn-look details")
        self.assertIsNone(english.name("Galaxy - Hose mit Racer-Ausschnitt"), "the rest must still be known")

    def test_an_before_a_vowel_sound(self):
        # "im" is "in a": English says "an" before a vowel sound, and "a" before any other.
        for german, said in (("Pullover im Oversized Fit", "Jumper in an oversized fit"),
                             ("T-Shirt im Oversize-Fit", "T-shirt in an oversized fit"),
                             ("Hemd im Oxford-Fit", "Shirt in an Oxford fit"),
                             ("Oversized T-Shirt im kastigen Fit", "Oversized T-shirt in a boxy fit"),
                             ("Mantel im Relaxed Fit mit Wolle", "Coat in a relaxed fit with wool"),
                             ("Chinohose im Slim-Fit", "Chinos in a slim fit")):
            with self.subTest(german):
                self.assertEqual(english.name(german), said)
        for text, said in (("in a oversized fit", "in an oversized fit"), ("in an boxy fit", "in a boxy fit"),
                           ("a unisex fit", "a unisex fit"), ("a hour", "an hour"), ("an used look", "a used look")):
            with self.subTest(text):
                self.assertEqual(english._a_or_an(text), said)

    def test_a_model_name_that_only_looks_like_a_word_with_an_ending(self):
        # "Lowe" looks like the English "low" with German's "e", but German adds no endings to the English words it
        # borrows: it is a name, so the store's own words stay, and before a dash it stays as the model's name.
        self.assertIsNone(english.word("Lowe"))
        self.assertIsNone(english.name("Lowe Jeans"))
        self.assertEqual(english.name("Lowe - Weite Jeans"), "Lowe – wide jeans")
        for name in ("Slimes", "Standarde", "Boxyer", "Classice"):
            with self.subTest(name):
                self.assertIsNone(english.word(name))
        self.assertEqual(english.word("Normaler"), "regular", "a German word keeps its endings")
        self.assertTrue(english.NO_ENDINGS <= set(english.WORDS), "every English word without endings is in the list")

    def test_a_cut_said_after_the_garment_comes_first(self):
        self.assertEqual(english.name("Jeans Slim Tapered"), "Slim tapered jeans")
        self.assertEqual(english.name("Overshirt aus Twill Relaxed"), "Relaxed overshirt, twill")
        self.assertEqual(english.name("Blazer aus Wolle – Regular Fit"), "Blazer, wool – regular fit")

    def test_no_outside_service_is_asked(self):
        english.name.cache_clear()
        with mock.patch.object(socket, "socket", side_effect=AssertionError("a connection was opened")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("a connection was opened")):
            for german, said in NAMES.items():
                self.assertEqual(english.name(german), said)



class APieceNamedByWhatWasPicked(unittest.TestCase):
    # Review N4: "Dark brown derby shoes" over "Penny loafers" read as an error. Where the product plainly is another
    # kind than the piece's name says, the piece is called by the product's kind; otherwise it keeps its name.
    def test_the_products_kind_takes_the_place_of_the_pieces(self):
        self.assertEqual(english.as_picked("Dark brown derby shoes", "leather derby", "Loafer aus Leder"), "Dark brown loafers")
        self.assertEqual(english.as_picked("Black Chelsea boots", "leather chelsea", "Derby-Schuhe"), "Black derby shoes")

    def test_a_product_of_the_pieces_kind_or_of_no_kind_said_keeps_the_name(self):
        for product in ("Derby-Schuhe aus Leder", "Schuhe aus Leder", "", "Leather shoes"):
            with self.subTest(product):
                self.assertEqual(english.as_picked("Dark brown derby shoes", "leather derby", product), "Dark brown derby shoes")
        self.assertEqual(english.as_picked("Navy tee", "heavyweight", "Loafer"), "Navy tee", "a piece of no kind")

    def test_a_name_he_wrote_himself_gets_the_kind_after_it(self):
        self.assertEqual(english.as_picked("Brown derbies", "leather derby", "Penny Loafer"), "Brown derbies (loafers)")

if __name__ == "__main__":
    unittest.main()
