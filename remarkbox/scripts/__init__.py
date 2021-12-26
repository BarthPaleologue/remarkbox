import argparse


def base_parser(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-c", "--config", default="development.ini")
    return parser
