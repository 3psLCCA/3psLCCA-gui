from pylatex import Figure, NoEscape

from ..latex_helpers import paragraph, section


def _framework_figure() -> str:
    figure = Figure(position="H")
    figure.add_image("../pdf_generation_v3/images/image_1.png", width=NoEscape(r"0.82\textwidth"))
    figure.add_caption("3PS-LCC framework")
    return figure.dumps()


def introduction_to_latex() -> str:
    return "\n\n".join([
        section("Introduction to Life Cycle Cost Assessment"),
        paragraph(
            "Life Cycle Cost is the total cost incurred by the bridge throughout its life. " \
            "This report presents Life Cycle Cost Assessment (LCCA) based on the Three Pillars of Sustainability-Life Cycle Cost (3PS-LCC) framework, which considers the economic, social, and environmental pillars over the selected analysis period. " \
            "The various life cycle stages and sustainability pillars considered in the 3PS-LCC framework are illustrated in Figure 1."
        ),
        _framework_figure(),
    ])
